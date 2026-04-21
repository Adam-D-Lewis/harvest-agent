"""Snapshot today's entries and render a before-vs-after change summary.

Used by the REPL to show a deterministic, code-enforced summary of what
changed on the current day after each agent turn. Complements the agent's
own natural-language summary — the diff is a trustworthy source for the
user to verify against the model's interpretation.

Scope: today only. If the user edits a different day, the diff will be
empty (fine — the agent still answers). Extending to arbitrary dates would
require tracking which dates each tool call touched; deferred.
"""

from __future__ import annotations

import json
from typing import Any

from harvest_agent import harvest_cli


def fetch_today_entries() -> list[dict[str, Any]]:
    """Return today's entries as a flat list of harvest entry dicts.

    Empty list on any failure (CLI error, null payload, malformed JSON).
    Callers treat an empty list the same as "no entries today" — the diff
    will simply compute against that baseline. A silent fetch failure means
    the diff may be misleading for that single turn; this is acceptable
    given the primary action (logging) is unaffected.
    """
    result = harvest_cli.run(["view", "today", "--json"])
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
    in the tools module (avoids a circular-ish import and keeps this module
    self-contained).
    """
    project = entry.get("project") or {}
    task = entry.get("task") or {}
    return {
        "id": entry.get("id"),
        "hours": entry.get("hours"),
        "notes": entry.get("notes") or "",
        "project": project.get("name") if isinstance(project, dict) else "",
        "task": task.get("name") if isinstance(task, dict) else "",
    }


def _format_entry_line(prefix: str, e: dict[str, Any]) -> str:
    hours = e["hours"]
    notes = f'  "{e["notes"]}"' if e["notes"] else ""
    return f'  {prefix} {e["project"]} / {e["task"]}  {hours}h{notes}'


def _format_modified_line(entry_id: Any, before: dict[str, Any], after: dict[str, Any]) -> str:
    parts: list[str] = []
    for field in ("hours", "project", "task", "notes"):
        if before[field] != after[field]:
            parts.append(f"{field} {before[field]!r} → {after[field]!r}")
    return f"  ~ Entry {entry_id}: " + ", ".join(parts)


def format_changes(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> str:
    """Return a human-readable summary of changes between two entry lists.

    Returns an empty string when nothing changed (REPL prints nothing).
    Entries are matched by ID: new IDs are additions, missing IDs are
    deletions, same ID with different fields is a modification.
    """
    before_by_id = {_entry_summary(e)["id"]: _entry_summary(e) for e in before}
    after_by_id = {_entry_summary(e)["id"]: _entry_summary(e) for e in after}

    added_ids = sorted(set(after_by_id) - set(before_by_id), key=lambda x: (x is None, x))
    removed_ids = sorted(set(before_by_id) - set(after_by_id), key=lambda x: (x is None, x))
    common_ids = set(before_by_id) & set(after_by_id)
    modified_ids = sorted(
        [i for i in common_ids if before_by_id[i] != after_by_id[i]],
        key=lambda x: (x is None, x),
    )

    if not added_ids and not removed_ids and not modified_ids:
        return ""

    lines = ["Changes this turn:"]
    for i in added_ids:
        lines.append(_format_entry_line("+ Added:", after_by_id[i]))
    for i in removed_ids:
        lines.append(_format_entry_line("- Deleted:", before_by_id[i]))
    for i in modified_ids:
        lines.append(_format_modified_line(i, before_by_id[i], after_by_id[i]))

    total_before = sum((e.get("hours") or 0) for e in before)
    total_after = sum((e.get("hours") or 0) for e in after)
    if total_before != total_after:
        lines.append(f"  Total: {total_before}h → {total_after}h")

    return "\n".join(lines)
