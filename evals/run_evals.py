"""Run the harvest-agent eval dataset against the current model.

Usage:
    # Default (whatever HARVEST_AGENT_MODEL / ANTHROPIC_API_KEY resolves to)
    pixi run evals

    # Against Qwen3-Coder-Next via local llama.cpp
    HARVEST_AGENT_BASE_URL=http://localhost:8080/v1 \\
    HARVEST_AGENT_MODEL=Qwen3-Coder-Next \\
    pixi run evals

    # Run a single case with full debug output
    pixi run evals -- --case shortcut_acme --verbose

    # Substring match — runs all shortcut_* cases
    pixi run evals -- --case shortcut -v

Output: a pydantic_evals report showing pass/fail per case and category totals.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from evals.cases import ALL_CASES, build_dataset
from evals.task import AgentRunOutput, run_agent_task
from harvest_agent.agent import _describe_model, _resolve_model


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run harvest-agent evals.")
    p.add_argument(
        "--case", "-c",
        help="Run only cases whose name contains this substring.",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print full agent output (text, tool calls, CLI invocations) for each case.",
    )
    return p.parse_args()


def _print_banner():
    model = _resolve_model()
    print(f"\n{'=' * 70}")
    print(f" harvest-agent evals — model: {_describe_model(model)}")
    print(f"{'=' * 70}\n")


def _print_category_summary(report):
    """Group cases by metadata.category and show per-category pass rates."""
    totals: dict[str, list[int]] = {}  # category -> [passed, total]
    for case_report in report.cases:
        meta = case_report.metadata
        category = getattr(meta, "category", None) or "(uncategorized)"
        totals.setdefault(category, [0, 0])
        totals[category][1] += 1
        # A case "passes" if every evaluator returned a truthy value.
        all_passed = all(
            bool(getattr(r, "value", False))
            for r in case_report.assertions.values()
        )
        if all_passed:
            totals[category][0] += 1

    print("\nPer-category pass rate:")
    for category, (passed, total) in sorted(totals.items()):
        pct = (passed / total * 100) if total else 0
        print(f"  {category:<20} {passed}/{total}  ({pct:.0f}%)")


def _print_failures(report):
    """Print details for any failing cases so we can see the assertion reasons."""
    failures = []
    for case_report in report.cases:
        for name, result in case_report.assertions.items():
            if not bool(getattr(result, "value", False)):
                failures.append((case_report.name, name, result))
    if not failures:
        return
    print("\nFailure details:")
    for case_name, evaluator_name, result in failures:
        reason = getattr(result, "reason", None) or "<no reason>"
        print(f"  [{case_name}] {evaluator_name}: {reason}")


def _print_verbose_output(case_name: str, prompt: str, output: AgentRunOutput):
    """Print full diagnostic info for a single eval case."""
    print(f"\n{'─' * 70}")
    print(f"  Case: {case_name}")
    print(f"  Prompt: {prompt}")
    print(f"{'─' * 70}")

    print(f"\n  Agent text response:")
    for line in (output.text or "(empty)").splitlines():
        print(f"    {line}")

    if output.tool_calls:
        print(f"\n  Tool calls ({len(output.tool_calls)}):")
        for tc in output.tool_calls:
            print(f"    {tc.name}({tc.args})")
    else:
        print(f"\n  Tool calls: (none)")

    if output.cli_invocations:
        print(f"\n  CLI invocations ({len(output.cli_invocations)}):")
        for inv in output.cli_invocations:
            print(f"    harvest {' '.join(inv)}")
    else:
        print(f"\n  CLI invocations: (none)")
    print()


async def _run_verbose(case_filter: str | None) -> int:
    """Run matching cases one-by-one with full output, bypassing pydantic_evals."""
    cases = ALL_CASES
    if case_filter:
        cases = [c for c in cases if case_filter in c.name]
        if not cases:
            print(f"No cases match '{case_filter}'. Available cases:")
            for c in ALL_CASES:
                print(f"  {c.name}")
            return 1
    print(f"Running {len(cases)} case(s) in verbose mode...\n")
    for case in cases:
        output = await run_agent_task(case.inputs)
        _print_verbose_output(case.name, case.inputs.prompt, output)
    return 0


async def main() -> int:
    args = _parse_args()
    _print_banner()

    if args.verbose:
        return await _run_verbose(args.case)

    dataset = build_dataset(case_filter=args.case)
    if not dataset.cases:
        print(f"No cases match '{args.case}'. Available cases:")
        for c in ALL_CASES:
            print(f"  {c.name}")
        return 1

    report = await dataset.evaluate(run_agent_task, max_concurrency=1)
    report.print(include_input=False, include_output=False)
    _print_category_summary(report)
    _print_failures(report)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
