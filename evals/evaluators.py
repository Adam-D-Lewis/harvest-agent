"""Custom evaluators for harvest-agent eval cases.

Each evaluator inspects an `AgentRunOutput` (produced by `task.run_agent_task`)
and returns a bool / EvaluationReason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext

from evals.task import AgentRunOutput, EvalInput, EvalMeta, ToolCall

Ctx = EvaluatorContext[EvalInput, AgentRunOutput, EvalMeta]


def _find_calls(output: AgentRunOutput, name: str) -> list[ToolCall]:
    return [c for c in output.tool_calls if c.name == name]


@dataclass
class ToolCalledWith(Evaluator[EvalInput, AgentRunOutput, EvalMeta]):
    """Pass iff a tool with `name` was called with args containing each kv in `required_args`.

    If `required_args` is empty, any call to the named tool passes.
    """

    name: str
    required_args: dict[str, Any] = field(default_factory=dict)

    def evaluate(self, ctx: Ctx) -> EvaluationReason:
        calls = _find_calls(ctx.output, self.name)
        if not calls:
            return EvaluationReason(
                value=False,
                reason=f"tool '{self.name}' was not called (actual: {[c.name for c in ctx.output.tool_calls]})",
            )
        for call in calls:
            if all(call.args.get(k) == v for k, v in self.required_args.items()):
                return EvaluationReason(value=True, reason=f"matched call: {call.args}")
        actual_args = [c.args for c in calls]
        return EvaluationReason(
            value=False,
            reason=f"tool '{self.name}' called but args didn't match required={self.required_args}, actual={actual_args}",
        )


@dataclass
class ToolNotCalled(Evaluator[EvalInput, AgentRunOutput, EvalMeta]):
    """Pass iff the named tool was NOT called.

    If `name` is None, passes iff NO tools were called at all.
    """

    name: str | None = None

    def evaluate(self, ctx: Ctx) -> EvaluationReason:
        if self.name is None:
            if not ctx.output.tool_calls:
                return EvaluationReason(value=True, reason="no tools called")
            return EvaluationReason(
                value=False,
                reason=f"expected no tool calls, got {[c.name for c in ctx.output.tool_calls]}",
            )
        calls = _find_calls(ctx.output, self.name)
        if not calls:
            return EvaluationReason(value=True, reason=f"tool '{self.name}' was not called (ok)")
        return EvaluationReason(
            value=False,
            reason=f"tool '{self.name}' should not have been called, but was {len(calls)}x",
        )


@dataclass
class HarvestCLIInvokedWith(Evaluator[EvalInput, AgentRunOutput, EvalMeta]):
    """Pass iff the harvest CLI was invoked at least once with matching args.

    This is the post-processing check — it inspects what `harvest_cli.run`
    was actually called with, AFTER the tools resolved shortcuts, parsed
    dates, and rounded hours. Use this for end-to-end correctness checks
    rather than `ToolCalledWith` (which inspects what the LLM passed,
    before tool processing).

    Match semantics:
    - `subcmd` must equal `cli_args[0]`
    - Each `(index, value)` in `positional` must match `cli_args[index]`
      (1-indexed since position 0 is the subcmd)
    - Each `(flag, value)` in `flags` must appear in the args list with
      the matching value following it

    Example for `harvest log "Web Redesign" "Programming" 2.0 "" --date 2026-04-13`:
        HarvestCLIInvokedWith(
            subcmd="log",
            positional={1: "Web Redesign", 2: "Programming"},
            flags={"--date": "2026-04-13"},
        )
    """

    subcmd: str
    positional: dict[int, str] = field(default_factory=dict)
    flags: dict[str, str] = field(default_factory=dict)

    def evaluate(self, ctx: Ctx) -> EvaluationReason:
        if not ctx.output.cli_invocations:
            return EvaluationReason(
                value=False, reason="no harvest CLI invocations recorded"
            )
        for cli_args in ctx.output.cli_invocations:
            if not cli_args or cli_args[0] != self.subcmd:
                continue
            if not all(
                idx < len(cli_args) and cli_args[idx] == val
                for idx, val in self.positional.items()
            ):
                continue
            ok = True
            for flag, val in self.flags.items():
                if flag not in cli_args:
                    ok = False
                    break
                idx = cli_args.index(flag)
                if idx + 1 >= len(cli_args) or cli_args[idx + 1] != val:
                    ok = False
                    break
            if ok:
                return EvaluationReason(value=True, reason=f"matched: {cli_args}")
        return EvaluationReason(
            value=False,
            reason=(
                f"no CLI invocation matched subcmd={self.subcmd!r} "
                f"positional={self.positional} flags={self.flags}; "
                f"actual: {ctx.output.cli_invocations}"
            ),
        )


@dataclass
class HarvestLogProjectIsOneOf(Evaluator[EvalInput, AgentRunOutput, EvalMeta]):
    """Pass iff every successful `harvest log ...` invocation used a project from `allowed`.

    Use this to catch silent project substitution: a weak model that, told the
    user wants 'mobile app' (which doesn't exist), picks a different real
    project and logs anyway. The eval should fail loudly in that case.

    Passes if NO `log` invocation happened at all (refusal is acceptable).
    Fails if any `log` invocation has a project that isn't in `allowed`.

    The harvest log CLI shape is `harvest log <project> <task> <hours> <notes>
    --date <date>`, so the project sits at index 1.
    """

    allowed: list[str]

    def evaluate(self, ctx: Ctx) -> EvaluationReason:
        log_calls = [a for a in ctx.output.cli_invocations if a and a[0] == "log"]
        if not log_calls:
            return EvaluationReason(value=True, reason="no log invocations (refusal is acceptable)")
        bad = [a for a in log_calls if len(a) < 2 or a[1] not in self.allowed]
        if bad:
            return EvaluationReason(
                value=False,
                reason=(
                    f"log invoked with project not in allowed={self.allowed}; "
                    f"actual: {[a[1] if len(a) > 1 else '<missing>' for a in bad]}"
                ),
            )
        return EvaluationReason(
            value=True,
            reason=f"all {len(log_calls)} log invocations used an allowed project",
        )


def _normalize_text(s: str) -> str:
    """Normalise text for substring matching: lowercase + replace curly apostrophes."""
    return (s or "").lower().replace("\u2019", "'").replace("\u2018", "'")


@dataclass
class OutputContainsAny(Evaluator[EvalInput, AgentRunOutput, EvalMeta]):
    """Case-insensitive substring match: pass iff output.text contains any of `substrings`.

    Curly/smart quotes (\u2018 \u2019) are normalised to straight ASCII before
    matching, so a needle of `"haven't"` matches a haystack of `"haven\u2019t"`.
    """

    substrings: list[str]

    def evaluate(self, ctx: Ctx) -> EvaluationReason:
        text = _normalize_text(ctx.output.text)
        hits = [s for s in self.substrings if _normalize_text(s) in text]
        if hits:
            return EvaluationReason(value=True, reason=f"found: {hits}")
        return EvaluationReason(
            value=False,
            reason=f"none of {self.substrings} found in: {ctx.output.text!r}",
        )
