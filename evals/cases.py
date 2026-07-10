"""The eval dataset — every Case the agent is graded on.

Organized by category:

1. tool_selection    — does the agent pick the right tool for the request?
2. shortcut          — does it resolve shortcut names to real project/task strings?
3. relative_date     — does it compute "yesterday", "next Monday", etc. correctly?
4. empty_state       — does it handle `view_today` returning null cleanly?
5. cancel_respect    — does it respect a cancelled destructive op (no retry, no dupe)?
6. hallucination     — does it refuse requests we don't have a tool for?

We deliberately don't have a "rounding" category — hours are rounded
programmatically in `tools.log_time`/`edit_entry` and covered by unit tests.
Paying LLM inference cost to re-verify Python arithmetic is waste.

Frozen "today" for all cases: Wednesday 2026-04-08 (chosen so every date in
the relative_date category is unambiguous).
"""

from __future__ import annotations

from datetime import date

from pydantic_evals import Case, Dataset

from evals.evaluators import (
    HarvestCLIInvokedWith,
    HarvestLogProjectIsOneOf,
    OutputContainsAny,
    ToolCalledWith,
    ToolNotCalled,
)
from evals.task import AgentRunOutput, EvalInput, EvalMeta

TODAY = date(2026, 4, 8)  # Wednesday


# ---------- Category 1: tool selection ----------

TOOL_SELECTION_CASES = [
    Case(
        name="view_today_simple",
        inputs=EvalInput(prompt="What did I log today?", today=TODAY),
        metadata=EvalMeta(category="tool_selection"),
        evaluators=[ToolCalledWith(name="view_today")],
    ),
    Case(
        name="status_week_progress",
        inputs=EvalInput(prompt="What's my hour status for the week so far?", today=TODAY),
        metadata=EvalMeta(category="tool_selection"),
        # Either status OR view_week answers this; accept either by running both
        # evaluators, each of which can pass independently.
        evaluators=[
            OutputContainsAny(substrings=["25.5", "71", "week"]),  # soft text check
        ],
    ),
    Case(
        name="view_last_week",
        inputs=EvalInput(
            prompt="Show me my entries from last week.",
            fixture="multiple_entries",
            today=TODAY,
        ),
        metadata=EvalMeta(category="tool_selection"),
        evaluators=[
            # Either view_week(offset=-1) or view_range are acceptable.
            # We check that SOME view tool was called and didn't hit view_today.
            ToolNotCalled(name="view_today"),
        ],
    ),
    Case(
        name="list_projects",
        inputs=EvalInput(prompt="What projects can I bill time to?", today=TODAY),
        metadata=EvalMeta(category="tool_selection"),
        evaluators=[ToolCalledWith(name="list_projects")],
    ),
    Case(
        name="stop_timer",
        inputs=EvalInput(prompt="Stop my running timer.", today=TODAY),
        metadata=EvalMeta(category="tool_selection"),
        evaluators=[ToolCalledWith(name="stop_timer")],
    ),
]


# ---------- Category 2: shortcut resolution ----------

SHORTCUT_CASES = [
    Case(
        name="shortcut_acme",
        inputs=EvalInput(
            prompt='Log 2 hours to the "acme" shortcut with note "standup" for today.',
            today=TODAY,
        ),
        metadata=EvalMeta(category="shortcut"),
        evaluators=[
            HarvestCLIInvokedWith(
                subcmd="log",
                positional={1: "Web Redesign", 2: "Programming"},
            ),
        ],
    ),
    Case(
        name="shortcut_mobile_meeting",
        inputs=EvalInput(
            prompt='Log 1 hour to "mobile meeting" for today with no notes.',
            today=TODAY,
        ),
        metadata=EvalMeta(category="shortcut"),
        evaluators=[
            HarvestCLIInvokedWith(
                subcmd="log",
                positional={1: "Mobile App v2", 2: "Meetings / Standups"},
            ),
        ],
    ),
    Case(
        name="shortcut_pto",
        inputs=EvalInput(
            prompt="Log 8 hours to pto for today.",
            today=TODAY,
        ),
        metadata=EvalMeta(category="shortcut"),
        evaluators=[
            HarvestCLIInvokedWith(
                subcmd="log",
                positional={1: "PTO (PTO, Sick Leave, Parental Leave)", 2: "PTO"},
            ),
        ],
    ),
]


# ---------- Category 3: relative dates ----------
#
# Today is Wednesday 2026-04-08 unless otherwise noted.
#
# Note: "next <day>" and "last <day>" are no longer accepted by the parser
# (both are ambiguous in conversational English). The new regression cases
# use the unambiguous "Thursday of next week" / "Tuesday of last week"
# phrasings, which the model should resolve by reading the 3-week date
# table in the system prompt.
def _date_case(name: str, prompt_phrase: str, today: date, expected_iso: str, description: str = "") -> Case:
    """Build a relative-date case that checks the harvest CLI received the right --date.

    The agent's job is to pass `prompt_phrase` to the tool's `date` arg as-is;
    the tool then parses it. Both halves are tested by checking what the CLI
    actually received.
    """
    return Case(
        name=name,
        inputs=EvalInput(
            prompt=f'Log 1 hour to acme with note "" for {prompt_phrase}.',
            today=today,
        ),
        metadata=EvalMeta(category="relative_date", description=description),
        evaluators=[
            HarvestCLIInvokedWith(subcmd="log", flags={"--date": expected_iso}),
        ],
    )


RELATIVE_DATE_CASES = [
    _date_case("date_today", "today", TODAY, "2026-04-08", "today (Wed 2026-04-08)"),
    _date_case("date_yesterday", "yesterday", TODAY, "2026-04-07", "yesterday"),
    _date_case("date_tomorrow", "tomorrow", TODAY, "2026-04-09", "tomorrow"),
    _date_case("date_this_friday", "this Friday", TODAY, "2026-04-10", "this Friday (upcoming)"),
    _date_case(
        "date_thursday_of_next_week_via_table",
        "Thursday of next week",
        TODAY,
        "2026-04-16",
        "regression: model must read next-week dates off the 3-week table",
    ),
    _date_case(
        "date_tuesday_of_last_week_via_table",
        "Tuesday of last week",
        TODAY,
        "2026-03-31",
        "regression: model must read last-week dates off the 3-week table",
    ),
    _date_case(
        "date_bare_weekday_defaults_to_past",
        "Monday",
        TODAY,
        "2026-04-06",
        "regression: a bare weekday defaults to the most recent PAST "
        "occurrence (this Mon 2026-04-06), since hours are logged after the "
        "fact — not next week's Monday",
    ),
]


# ---------- Category 5: empty state handling ----------

EMPTY_STATE_CASES = [
    Case(
        name="empty_today",
        inputs=EvalInput(prompt="What did I log today?", fixture="empty", today=TODAY),
        metadata=EvalMeta(category="empty_state"),
        evaluators=[
            ToolCalledWith(name="view_today"),
            OutputContainsAny(substrings=["no entries", "nothing", "no time", "haven't", "no hours"]),
        ],
    ),
    Case(
        name="empty_week_summary",
        inputs=EvalInput(
            prompt="Summarize today's entries in one sentence.",
            fixture="empty",
            today=TODAY,
        ),
        metadata=EvalMeta(category="empty_state"),
        evaluators=[
            OutputContainsAny(substrings=["no entries", "nothing", "no time", "haven't", "empty"]),
        ],
    ),
]


# ---------- Category 6: confirmation respect ----------

CANCEL_CASES = [
    Case(
        name="cancelled_delete_reports_cancellation",
        inputs=EvalInput(
            prompt="Delete entry 99.",
            fixture="entry_99",
            today=TODAY,
            confirm_accepts=False,  # user 'declines' the confirmation
        ),
        metadata=EvalMeta(
            category="cancel_respect",
            description="delete_entry should see cancelled result; agent relays it",
        ),
        evaluators=[
            ToolCalledWith(name="delete_entry"),
            OutputContainsAny(substrings=["cancel", "not delete", "didn't delete", "still"]),
        ],
    ),
    Case(
        name="cancelled_edit_reports_cancellation",
        inputs=EvalInput(
            prompt="Edit entry 99 to be 2 hours instead.",
            fixture="entry_99",
            today=TODAY,
            confirm_accepts=False,
        ),
        metadata=EvalMeta(
            category="cancel_respect",
            description="edit_entry should see cancelled result; agent relays it",
        ),
        evaluators=[
            ToolCalledWith(name="edit_entry"),
            OutputContainsAny(substrings=["cancel", "not edit", "didn't", "still"]),
        ],
    ),
]


# ---------- Category 7: hallucination refusal ----------

HALLUCINATION_CASES = [
    Case(
        name="refuse_rename_project",
        inputs=EvalInput(
            prompt="Rename the Web Redesign project to Foo.",
            today=TODAY,
        ),
        metadata=EvalMeta(
            category="hallucination",
            description="we have no 'rename project' tool; agent should refuse",
        ),
        evaluators=[
            # No log/edit/delete tool should have been called
            ToolNotCalled(name="log_time"),
            ToolNotCalled(name="edit_entry"),
            ToolNotCalled(name="delete_entry"),
            OutputContainsAny(
                substrings=["can't", "cannot", "don't have", "do not have", "unable", "no way", "not able"]
            ),
        ],
    ),
    Case(
        name="refuse_create_project",
        inputs=EvalInput(
            prompt='Create a new project called "TestProj".',
            today=TODAY,
        ),
        metadata=EvalMeta(category="hallucination"),
        evaluators=[
            ToolNotCalled(name="log_time"),
            ToolNotCalled(name="edit_entry"),
            OutputContainsAny(
                substrings=["can't", "cannot", "don't have", "do not have", "unable", "no way", "not able"]
            ),
        ],
    ),
    Case(
        name="refuse_submit_timesheet",
        inputs=EvalInput(
            prompt="Submit my timesheet for approval.",
            today=TODAY,
        ),
        metadata=EvalMeta(
            category="hallucination",
            description="harvest CLI has submit, but we intentionally didn't expose it",
        ),
        evaluators=[
            ToolNotCalled(name="log_time"),
            ToolNotCalled(name="edit_entry"),
            ToolNotCalled(name="delete_entry"),
            OutputContainsAny(
                substrings=["can't", "cannot", "don't have", "do not have", "unable", "no way", "not able", "no tool"]
            ),
        ],
    ),
]


# ---------- Category 8: project / task validation ----------

PROJECT_VALIDATION_CASES = [
    Case(
        name="typo_project_name",
        inputs=EvalInput(
            prompt="Log 2 hours to Web Rdesign for programming on standup notes.",
            today=TODAY,
        ),
        metadata=EvalMeta(
            category="project_validation",
            description="model must either retry with canonical 'Web Redesign' or refuse — never silently substitute",
        ),
        evaluators=[
            # Hard rule: if harvest log was called at all, it must have been
            # called with the canonical "Web Redesign". Refusal (no log call)
            # is also acceptable. The failure mode we MUST catch is silent
            # substitution to a different real project (e.g. Mobile App v2).
            HarvestLogProjectIsOneOf(allowed=["Web Redesign"]),
        ],
    ),
    Case(
        name="invented_project_refused",
        inputs=EvalInput(
            prompt="Log 1 hour to the Imaginary Project for stuff.",
            today=TODAY,
        ),
        metadata=EvalMeta(
            category="project_validation",
            description="model must refuse — no log call may reach harvest",
        ),
        evaluators=[
            # No log invocation may happen at all. There is no real project
            # named "Imaginary Project", so any successful log to anything
            # else is silent substitution and must fail.
            HarvestLogProjectIsOneOf(allowed=[]),
        ],
    ),
]


# ---------- Combined dataset ----------

ALL_CASES: list[Case] = [
    *TOOL_SELECTION_CASES,
    *SHORTCUT_CASES,
    *RELATIVE_DATE_CASES,
    *EMPTY_STATE_CASES,
    *CANCEL_CASES,
    *HALLUCINATION_CASES,
    *PROJECT_VALIDATION_CASES,
]


def build_dataset(case_filter: str | None = None) -> Dataset[EvalInput, AgentRunOutput, EvalMeta]:
    cases = ALL_CASES
    if case_filter:
        cases = [c for c in cases if case_filter in c.name]
    return Dataset[EvalInput, AgentRunOutput, EvalMeta](name="harvest-agent", cases=cases)
