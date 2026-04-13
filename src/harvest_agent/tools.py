"""Tool functions exposed to the PydanticAI agent.

Each function is a thin wrapper over `harvest_cli.run`. They will be registered
as `@agent.tool_plain` in `agent.py`. Defining them as plain functions here
makes them trivially unit-testable.

Module-level state: `configure()` is called by `agent._build_agent` at startup
to install the user's shortcut table and (optionally) an override "today" date
used by the relative-date parser. We keep this in module state — instead of
plumbing config through every tool's signature — so the LLM's tool schema
stays minimal. The state is read-only after configure() runs.
"""

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from harvest_agent import confirm, harvest_cli
from harvest_agent.config import Shortcut
from harvest_agent.project_index import ProjectIndex


@dataclass
class _ToolContext:
    shortcuts: dict[str, Shortcut] = field(default_factory=dict)
    today_override: date | None = None
    project_index: ProjectIndex = field(default_factory=dict)


_context = _ToolContext()


def configure(
    shortcuts: list[Shortcut] | None = None,
    today: date | None = None,
    project_index: ProjectIndex | None = None,
) -> None:
    """Install the user's shortcut table, fake 'today', and project index.

    Called once by `agent._build_agent`. Tests and evals may call it directly
    to control state. Safe to call repeatedly — each call replaces prior state.
    An empty (or omitted) `project_index` disables project/task validation.
    """
    global _context
    _context = _ToolContext(
        shortcuts={s.name: s for s in (shortcuts or [])},
        today_override=today,
        project_index=project_index or {},
    )


def _today() -> date:
    """Return the current 'today' — either the configured override or real today."""
    return _context.today_override or date.today()


def _resolve_shortcut(name: str) -> Shortcut | None:
    """Return the Shortcut if `name` matches a configured shortcut, else None."""
    return _context.shortcuts.get(name)


def _parse_date(value: str) -> str:
    """Parse a user-facing date string into a YYYY-MM-DD ISO date.

    Accepts:
    - ISO YYYY-MM-DD (passed through unchanged)
    - "today" / "yesterday" / "tomorrow"
    - "this/last/next <dayname>" (dayname: monday..sunday or mon..sun)
    - bare "<dayname>" — treated as the upcoming occurrence (today if today
      is already that day)

    Raises ValueError for anything else so the caller can report a clear
    error to the LLM.
    """
    raw = value.strip().lower()
    if not raw:
        return _today().isoformat()

    # Pass ISO dates through.
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        pass

    today = _today()

    if raw == "today":
        return today.isoformat()
    if raw == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    if raw == "tomorrow":
        return (today + timedelta(days=1)).isoformat()

    day_names = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
        "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
    }

    parts = raw.split()
    today_dow = today.weekday()

    # "this <dayname>" — upcoming day in the current week (today if today
    # is the target). "next" and "last" are deliberately not parsed: both
    # are ambiguous in conversational English (e.g. "next Thursday" can mean
    # tomorrow or Thursday of next week; "last Tuesday" can mean yesterday or
    # Tuesday of last week). The system prompt's three-week date table is
    # the model's deterministic source for those.
    if len(parts) == 2 and parts[0] == "this" and parts[1] in day_names:
        target_dow = day_names[parts[1]]
        delta = (target_dow - today_dow) % 7
        return (today + timedelta(days=delta)).isoformat()

    # Bare "<dayname>" → upcoming
    if raw in day_names:
        target_dow = day_names[raw]
        delta = (target_dow - today_dow) % 7
        return (today + timedelta(days=delta)).isoformat()

    raise ValueError(
        f"Could not parse date {value!r}. Use YYYY-MM-DD (the 3-week date "
        "table in your system prompt lists nearby dates), or 'today', "
        "'yesterday', 'tomorrow', 'this <weekday>'."
    )


# ---------- Read-only tools (no confirmation needed) ----------


def view_today() -> dict[str, Any]:
    """View today's time entries as JSON."""
    return harvest_cli.run(["view", "today", "--json"])


def view_week(offset: int = 0) -> dict[str, Any]:
    """View a week's time entries as JSON.

    Args:
        offset: 0 for this week, -1 for last week, -2 for two weeks ago, etc.
    """
    args = ["view", "week"]
    if offset != 0:
        args.append(str(offset))
    args.append("--json")
    return harvest_cli.run(args)


def view_range(from_date: str, to_date: str) -> dict[str, Any]:
    """View entries in a date range as JSON.

    Args:
        from_date: YYYY-MM-DD start date.
        to_date: YYYY-MM-DD end date (inclusive).
    """
    return harvest_cli.run(["view", "--from", from_date, "--to", to_date, "--json"])


def list_projects() -> dict[str, Any]:
    """List all projects accessible to the current user."""
    return harvest_cli.run(["list", "projects"])


def list_tasks(project_id: int) -> dict[str, Any]:
    """List tasks for a specific project.

    Args:
        project_id: The numeric project ID from `list_projects`.
    """
    return harvest_cli.run(["list", "tasks", "-p", str(project_id)])


def status() -> dict[str, Any]:
    """Get the current week's hour status (e.g. "25.5h/36h (71%)")."""
    return harvest_cli.run(["status"])


# ---------- Additive tools (no confirmation needed) ----------


def _round_to_quarter(hours: float) -> float:
    """Round hours to the nearest 0.25 — Harvest convention."""
    return round(hours * 4) / 4


def log_time(project: str, task: str, hours: float, notes: str, date: str) -> dict[str, Any]:
    """Log a new time entry.

    The tool does several things automatically so the LLM doesn't have to:
    1. Shortcut resolution: if `project` matches a user-configured shortcut
       name (e.g. "acme", "mobile meeting"), both project AND task are
       replaced with the resolved values. In that case you may pass an
       empty string for `task` — it will be filled in. If you pass a
       non-empty `task`, it wins over the shortcut's task.
    2. Date parsing: `date` may be an ISO YYYY-MM-DD OR a natural-language
       value like "today", "yesterday", "tomorrow", "next Monday",
       "last Friday". The tool parses it deterministically.
    3. Hour rounding: `hours` is rounded to the nearest 0.25 automatically.
    4. Project/task validation: project and task are matched
       case-insensitively against the projects+tasks fetched at startup.
       Bogus names are rejected with a clear error before harvest is called.

    Args:
        project: Project name OR a shortcut name (e.g. "acme").
        task: Task name. Pass "" if using a shortcut that implies the task.
        hours: Hours to log (raw — will be rounded).
        notes: Description of the work; pass "" if none, NEVER omit.
        date: YYYY-MM-DD or a natural-language date. Required; pass "today"
            if the user didn't specify a date.
    """
    # Shortcut resolution.
    shortcut = _resolve_shortcut(project)
    if shortcut is not None:
        project = shortcut.project
        if not task:
            task = shortcut.task

    # Date parsing.
    try:
        parsed_date = _parse_date(date)
    except ValueError as e:
        return {"ok": False, "returncode": 0, "stdout": "", "stderr": str(e)}

    # Project/task validation (after shortcut resolution).
    validated = _validate_project_task(project, task)
    if isinstance(validated, str):
        return {"ok": False, "returncode": 0, "stdout": "", "stderr": validated}
    project, task = validated

    # Hour rounding.
    rounded = _round_to_quarter(hours)
    result = harvest_cli.run(["log", project, task, str(rounded), notes, "--date", parsed_date])

    notes_added = []
    if rounded != hours:
        notes_added.append(f"Hours rounded from {hours} to {rounded} (nearest 0.25)")
    if shortcut is not None:
        notes_added.append(
            f"Shortcut '{shortcut.name}' resolved to project='{shortcut.project}', task='{shortcut.task}'"
        )
    if parsed_date != date and not _looks_like_iso_date(date):
        notes_added.append(f"Date '{date}' parsed to {parsed_date}")
    if notes_added:
        result["tool_notes"] = notes_added
    return result


def _looks_like_iso_date(s: str) -> bool:
    try:
        date.fromisoformat(s.strip())
        return True
    except ValueError:
        return False


def _validate_project_task(project: str, task: str) -> tuple[str, str] | str:
    """Validate (project, task) against the configured project index.

    Returns a `(canonical_project, canonical_task)` tuple on success, or an
    error message string on failure. Empty `task` is allowed and passes
    through as ''.

    If the index is empty (startup fetch failed), validation is disabled and
    inputs are returned unchanged.
    """
    import difflib

    index = _context.project_index
    if not index:
        return (project, task)

    project_key = project.lower()
    info = index.get(project_key)
    if info is None:
        valid = sorted(p.canonical_name for p in index.values())
        suggestion = difflib.get_close_matches(project_key, list(index.keys()), n=1, cutoff=0.6)
        msg = f"Project {project!r} doesn't exist."
        if suggestion:
            canonical_suggestion = index[suggestion[0]].canonical_name
            msg += f" Did you mean {canonical_suggestion!r}?"
        msg += f" Valid projects: {', '.join(valid)}."
        return msg

    canonical_project = info.canonical_name
    if task == "":
        return (canonical_project, "")

    task_key = task.lower()
    canonical_task = info.tasks.get(task_key)
    if canonical_task is None:
        valid_tasks = sorted(info.tasks.values())
        suggestion = difflib.get_close_matches(task_key, list(info.tasks.keys()), n=1, cutoff=0.6)
        msg = f"Task {task!r} doesn't exist on project {canonical_project!r}."
        if suggestion:
            canonical_suggestion = info.tasks[suggestion[0]]
            msg += f" Did you mean {canonical_suggestion!r}?"
        msg += f" Valid tasks: {', '.join(valid_tasks)}."
        return msg

    return (canonical_project, canonical_task)


def start_timer(project: str, task: str, notes: str) -> dict[str, Any]:
    """Start a timer for the given project/task.

    Project and task are validated against the projects+tasks fetched at
    startup. Bogus names are rejected with a clear error before harvest is
    called.

    Args:
        project: Project name (case-insensitive; canonicalized for harvest).
        task: Task name within the project (case-insensitive).
        notes: Pass "" if none, NEVER omit (avoids TTY prompt).
    """
    validated = _validate_project_task(project, task)
    if isinstance(validated, str):
        return {"ok": False, "returncode": 0, "stdout": "", "stderr": validated}
    project, task = validated
    return harvest_cli.run(["start", project, task, notes])


def stop_timer() -> dict[str, Any]:
    """Stop the currently running timer, if any."""
    return harvest_cli.run(["stop"])


# ---------- Destructive tools (always confirm) ----------


def _parse_entries(stdout: str) -> list[dict[str, Any]]:
    """Parse a `harvest view --json` payload into a list of entries.

    The harvest CLI returns a top-level JSON array of entries, or `null` when
    there are no entries in the requested range. This helper normalises both
    cases (and any decode error) into a plain list.
    """
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    return []


def _summarize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Flatten a harvest entry to the fields we want to show in confirmation diffs.

    Harvest entries nest project/task/client as objects; flatten them to names so
    the before/after diff is human-readable.
    """
    project = entry.get("project") or {}
    task = entry.get("task") or {}
    return {
        "id": entry.get("id"),
        "date": entry.get("spent_date"),
        "hours": entry.get("hours"),
        "notes": entry.get("notes", ""),
        "project": project.get("name") if isinstance(project, dict) else project,
        "task": task.get("name") if isinstance(task, dict) else task,
        "locked": entry.get("is_locked", False),
    }


def _find_entry(entry_id: int) -> dict[str, Any] | None:
    """Locate an entry by ID, searching a window around today.

    The window extends 30 days back and 90 days forward. Forward bias because
    PTO and other planned time-off get logged ahead of time (weeks to months);
    past entries you're cleaning up are usually recent.

    Returns a flattened summary of the entry if found, else None.
    """
    today = _today()
    window_start = today - timedelta(days=30)
    window_end = today + timedelta(days=90)
    result = harvest_cli.run([
        "view", "--from", window_start.isoformat(), "--to", window_end.isoformat(), "--json"
    ])
    if not result["ok"]:
        return None
    for entry in _parse_entries(result["stdout"]):
        if entry.get("id") == entry_id:
            return _summarize_entry(entry)
    return None


def edit_entry(
    entry_id: int,
    hours: float | None = None,
    notes: str | None = None,
    project: str | None = None,
    task: str | None = None,
) -> dict[str, Any]:
    """Edit a time entry. Always shows a diff and asks for confirmation.

    Automatic processing:
    - Shortcut resolution: if `project` matches a shortcut name, it's
      replaced with the resolved project (and task too, unless you passed
      a non-empty task).
    - Hour rounding: `hours` (if provided) is rounded to the nearest 0.25.
    - Project/task validation: any provided project (and task) are matched
      against the project index.

    To change the task you must also pass `project`. Harvest cannot edit a
    task in isolation. Passing `task` without `project` returns an error.

    Pass only the fields you want to change. Returns a cancelled result if
    the user declines the confirmation prompt.
    """
    if task is not None and project is None:
        return {
            "ok": False,
            "returncode": 0,
            "stdout": "",
            "stderr": (
                "To change the task you must also pass project. "
                "Harvest cannot edit a task in isolation. Pass both project and task."
            ),
        }
    current = _find_entry(entry_id)
    before = current if current else {"id": entry_id, "note": "entry not found in -30d/+90d window"}

    # Shortcut resolution.
    shortcut = _resolve_shortcut(project) if project is not None else None
    if shortcut is not None:
        project = shortcut.project
        if task is None or task == "":
            task = shortcut.task

    # Project/task validation (after shortcut resolution).
    if project is not None:
        # If task wasn't passed (None), validate project alone by passing "".
        validated = _validate_project_task(project, task if task is not None else "")
        if isinstance(validated, str):
            return {"ok": False, "returncode": 0, "stdout": "", "stderr": validated}
        project = validated[0]
        if task is not None:
            task = validated[1]

    rounded_hours = _round_to_quarter(hours) if hours is not None else None

    after = dict(before)
    if rounded_hours is not None:
        after["hours"] = rounded_hours
    if notes is not None:
        after["notes"] = notes
    if project is not None:
        after["project"] = project
    if task is not None:
        after["task"] = task

    if not confirm.confirm_action(f"Edit entry {entry_id}", before, after):
        return {"ok": False, "returncode": 0, "stdout": "", "stderr": "user cancelled edit"}

    args = ["edit", "--id", str(entry_id)]
    if rounded_hours is not None:
        args.extend(["--hours", str(rounded_hours)])
    if notes is not None:
        args.extend(["--notes", notes])
    if project is not None:
        args.extend(["--project", project])
    if task is not None:
        args.extend(["--task", task])
    result = harvest_cli.run(args)

    tool_notes: list[str] = []
    if rounded_hours is not None and rounded_hours != hours:
        tool_notes.append(f"Hours rounded from {hours} to {rounded_hours} (nearest 0.25)")
    if shortcut is not None:
        tool_notes.append(
            f"Shortcut '{shortcut.name}' resolved to project='{shortcut.project}', task='{shortcut.task}'"
        )
    if tool_notes:
        result["tool_notes"] = tool_notes
    return result


def delete_entry(entry_id: int) -> dict[str, Any]:
    """Delete a time entry. Always shows the entry and asks for confirmation."""
    current = _find_entry(entry_id)
    before = current if current else {"id": entry_id, "note": "entry not found in -30d/+90d window"}

    if not confirm.confirm_action(f"Delete entry {entry_id}", before, None):
        return {"ok": False, "returncode": 0, "stdout": "", "stderr": "user cancelled delete"}

    return harvest_cli.run(["delete", "--id", str(entry_id)])
