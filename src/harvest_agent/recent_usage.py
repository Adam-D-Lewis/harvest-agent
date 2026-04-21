"""Build the set of (project, task) pairs the user has logged time against
recently. Used by `tools.log_time` to warn when the user logs to a pair they
haven't touched in the configured window.

Built once at agent startup via `harvest view --from X --to today --json`.
On any failure (CLI error, malformed JSON, missing fields), returns an empty
set and prints a one-line warning. Callers MUST treat an empty set as
"warning disabled, pass through".
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta

from harvest_agent import harvest_cli


def build_recent_pairs(window_days: int, today: date) -> set[tuple[str, str]]:
    """Fetch entries from the last `window_days` and return the set of
    lowercased (project_name, task_name) pairs used.

    The window is inclusive on both ends: from `today - window_days` through
    `today`. Pairs are lowercased to match the lookup convention in
    `project_index` and `tools._validate_project_task`.
    """
    from_date = today - timedelta(days=window_days)
    result = harvest_cli.run([
        "view", "--from", from_date.isoformat(), "--to", today.isoformat(), "--json",
    ])
    if not result["ok"]:
        print(
            f"warning: could not fetch recent entries ({result['stderr'].strip()}); "
            "unusual-project warning disabled this session.",
            file=sys.stderr,
        )
        return set()

    try:
        payload = json.loads(result["stdout"])
    except json.JSONDecodeError as e:
        print(
            f"warning: recent entries response was not valid JSON ({e}); "
            "unusual-project warning disabled this session.",
            file=sys.stderr,
        )
        return set()

    # harvest returns `null` for an empty range; treat the same as an empty
    # list (no pairs recorded → every log will warn). That's the right call —
    # if the user has logged zero hours in the window, everything is unusual.
    if payload is None:
        return set()
    if not isinstance(payload, list):
        return set()

    pairs: set[tuple[str, str]] = set()
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        project = entry.get("project") or {}
        task = entry.get("task") or {}
        if not isinstance(project, dict) or not isinstance(task, dict):
            continue
        pname = project.get("name")
        tname = task.get("name")
        if isinstance(pname, str) and pname and isinstance(tname, str) and tname:
            pairs.add((pname.lower(), tname.lower()))
    return pairs
