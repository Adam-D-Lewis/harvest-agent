"""Snapshot entries across a window around today and render a change summary.

Used by the REPL to show a deterministic, code-enforced summary of what
changed after each agent turn. Complements the agent's own natural-language
summary — the diff is a trustworthy source for the user to verify against
the model's interpretation.

Scope: today minus 30 days through today plus 90 days. The forward window
is generous because PTO and other planned time-off get logged ahead by
weeks or months; the past window matches the typical "cleaning up last
month" case. Changes outside this window won't appear in the diff.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from harvest_agent import harvest_cli

# Window applied on both sides of `today`. Matches the convention used by
# `tools._find_entry` so the diff covers the same range the user can edit.
DAYS_BACK = 30
DAYS_FORWARD = 90


def fetch_recent_entries(today: date) -> list[dict[str, Any]]:
    """Return entries in `today ± window` as a flat list of harvest entry dicts.

    Empty list on any failure (CLI error, null payload, malformed JSON).
    Callers treat an empty list the same as "no entries in window" — the diff
    will simply compute against that baseline. A silent fetch failure means
    the diff may be misleading for that single turn; this is acceptable
    given the primary action (logging) is unaffected.
    """
    from_date = today - timedelta(days=DAYS_BACK)
    to_date = today + timedelta(days=DAYS_FORWARD)
    result = harvest_cli.run([
        "view", "--from", from_date.isoformat(), "--to", to_date.isoformat(), "--json",
    ])
    if not result["ok"]:
        return []
    try:
        payload = json.loads(result["stdout"])
    except json.JSONDecodeError:
        return []
    if payload is None:
        return []
    if not isinstance(payload, list):
        return []
    return [e for e in payload if isinstance(e, dict)]


def _entry_summary(entry: dict[str, Any]) -> dict[str, Any]:
    """Flatten a harvest entry to the fields we use for diffing and display.

    Mirrors `tools._summarize_entry` but kept local so day_diff doesn't pull
    in the tools module.
    """
    project = entry.get("project") or {}
    task = entry.get("task") or {}
    return {
        "id": entry.get("id"),
        "spent_date": entry.get("spent_date") or "",
        "hours": entry.get("hours"),
        "notes": entry.get("notes") or "",
        "project": project.get("name") if isinstance(project, dict) else "",
        "task": task.get("name") if isinstance(task, dict) else "",
    }


def _format_entry_line(prefix: str, e: dict[str, Any]) -> str:
    notes = f'  "{e["notes"]}"' if e["notes"] else ""
    return f'    {prefix} {e["project"]} / {e["task"]}  {e["hours"]}h{notes}'


def _format_modified_line(entry_id: Any, before: dict[str, Any], after: dict[str, Any]) -> str:
    parts: list[str] = []
    for field in ("hours", "project", "task", "notes"):
        if before[field] != after[field]:
            parts.append(f"{field} {before[field]!r} → {after[field]!r}")
    return f"    ~ Entry {entry_id}: " + ", ".join(parts)


def format_changes(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> str:
    """Return a human-readable, date-grouped summary of changes between two
    entry lists.

    Returns an empty string when nothing changed (REPL prints nothing).
    Entries are matched by ID. Output groups changes under a header per
    affected date (most-recent-first), so multi-day changes (e.g. editing
    yesterday while also logging today) are unambiguous. Per-date totals
    are shown when a date's hours changed.
    """
    before_by_id = {e.get("id"): _entry_summary(e) for e in before if e.get("id") is not None}
    after_by_id = {e.get("id"): _entry_summary(e) for e in after if e.get("id") is not None}

    added_ids = set(after_by_id) - set(before_by_id)
    removed_ids = set(before_by_id) - set(after_by_id)
    common_ids = set(before_by_id) & set(after_by_id)
    modified_ids = {i for i in common_ids if before_by_id[i] != after_by_id[i]}

    if not added_ids and not removed_ids and not modified_ids:
        return ""

    # Gather every date that has a change, ordered most-recent-first.
    affected_dates: set[str] = set()
    for i in added_ids:
        affected_dates.add(after_by_id[i]["spent_date"])
    for i in removed_ids:
        affected_dates.add(before_by_id[i]["spent_date"])
    for i in modified_ids:
        affected_dates.add(after_by_id[i]["spent_date"])

    lines = ["Changes this turn:"]
    for d in sorted(affected_dates, reverse=True):
        lines.append(f"  {d}:")
        for i in sorted(added_ids, key=lambda x: (x is None, x)):
            if after_by_id[i]["spent_date"] == d:
                lines.append(_format_entry_line("+ Added:", after_by_id[i]))
        for i in sorted(removed_ids, key=lambda x: (x is None, x)):
            if before_by_id[i]["spent_date"] == d:
                lines.append(_format_entry_line("- Deleted:", before_by_id[i]))
        for i in sorted(modified_ids, key=lambda x: (x is None, x)):
            if after_by_id[i]["spent_date"] == d:
                lines.append(_format_modified_line(i, before_by_id[i], after_by_id[i]))
        total_before = sum(
            (e.get("hours") or 0) for e in before if e.get("spent_date") == d
        )
        total_after = sum(
            (e.get("hours") or 0) for e in after if e.get("spent_date") == d
        )
        if total_before != total_after:
            lines.append(f"    Total: {total_before}h → {total_after}h")

    return "\n".join(lines)
