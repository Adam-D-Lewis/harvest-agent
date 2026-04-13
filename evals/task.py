"""The eval task function: run the agent against a prompt, capture tool calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic_ai.messages import ModelResponse, ToolCallPart

from harvest_agent.agent import _build_agent
from harvest_agent.config import Config

from evals.fixtures import FIXTURES, patched_confirm, patched_harvest


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]


@dataclass
class AgentRunOutput:
    """What the eval task returns for each case.

    Evaluators inspect this — they should NOT rummage through PydanticAI
    internals.

    - `tool_calls`: what the LLM asked the agent to do (raw tool-call args).
    - `cli_invocations`: what the harvest CLI was actually invoked with,
      AFTER the tool's internal processing (shortcut resolution, date
      parsing, hour rounding). Use this for end-to-end checks like
      "did the CLI get the right project/task after shortcut resolution".
    """

    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    cli_invocations: list[list[str]] = field(default_factory=list)


@dataclass
class EvalInput:
    """Inputs for one eval case."""

    prompt: str
    fixture: str = "empty"
    today: date = field(default_factory=lambda: date(2026, 4, 8))
    confirm_accepts: bool = True


@dataclass
class EvalMeta:
    """Case metadata — used for grouping/reporting."""

    category: str
    description: str = ""


def _extract_tool_calls(messages) -> list[ToolCall]:
    """Walk PydanticAI messages and collect every tool call the model made."""
    calls: list[ToolCall] = []
    for msg in messages:
        if not isinstance(msg, ModelResponse):
            continue
        for part in msg.parts:
            if isinstance(part, ToolCallPart):
                try:
                    args = part.args_as_dict()
                except Exception:
                    args = {}
                calls.append(ToolCall(name=part.tool_name, args=args))
    return calls


def build_eval_config() -> Config:
    """Build a Config with a known set of shortcuts for eval cases.

    We don't read the user's real config — evals must be reproducible.
    """
    return Config.model_validate(
        {
            "user": {"name": "Test User"},
            "shortcut": [
                {
                    "name": "acme",
                    "project": "Web Redesign",
                    "task": "Programming",
                    "notes": "Default Acme Corp work",
                },
                {
                    "name": "acme meeting",
                    "project": "Web Redesign",
                    "task": "Meetings / Standups",
                },
                {
                    "name": "mobile",
                    "project": "Mobile App v2",
                    "task": "Backend API",
                },
                {
                    "name": "mobile meeting",
                    "project": "Mobile App v2",
                    "task": "Meetings / Standups",
                },
                {
                    "name": "pto",
                    "project": "PTO (PTO, Sick Leave, Parental Leave)",
                    "task": "PTO",
                },
            ],
            "behavior": {
                "flag_weekends": True,
                "notes": "Round hours to the nearest 0.25.",
            },
        }
    )


async def run_agent_task(inputs: EvalInput) -> AgentRunOutput:
    """Task function invoked by pydantic_evals for each Case."""
    from unittest.mock import patch

    fixture = FIXTURES[inputs.fixture]
    cfg = build_eval_config()

    # Wrap fixture.run so we can record the args harvest_cli.run was actually
    # called with. Evaluators that care about post-tool-processing (shortcut
    # resolution, date parsing, hour rounding) should inspect cli_invocations.
    cli_calls: list[list[str]] = []

    def recording_run(args: list[str], timeout: int = 30):
        cli_calls.append(list(args))
        return fixture.run(args, timeout)

    # The mock must be active BEFORE _build_agent runs, because
    # build_project_index() calls harvest_cli.run(["list", "projects", "--json"])
    # during agent construction.  Without this, the project index comes from
    # the real Harvest account instead of the fixture.
    #
    # A single patch is enough: tools.py and project_index.py both import
    # the same harvest_cli module object, so patching .run via one path
    # covers all callers.
    with patch("harvest_agent.tools.harvest_cli.run", side_effect=recording_run), \
         patched_confirm(inputs.confirm_accepts):
        agent = _build_agent(cfg, today=inputs.today)
        result = await agent.run(inputs.prompt)

    return AgentRunOutput(
        text=result.output or "",
        tool_calls=_extract_tool_calls(result.all_messages()),
        cli_invocations=cli_calls,
    )
