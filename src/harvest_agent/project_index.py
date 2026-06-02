"""Build and hold the canonical project/task index used for validation.

Built once at agent startup from `harvest list projects --json` and kept on
the tools `_ToolContext`. Lookups are case-insensitive: keys (in both the
top-level index and each ProjectInfo.tasks) are lowercased; the values carry
the canonical (correctly-cased) names that get passed back to harvest.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass

from harvest_agent import harvest_cli


@dataclass(frozen=True)
class ProjectInfo:
    canonical_name: str           # exact spelling from harvest
    tasks: dict[str, str]         # lowercased task name -> canonical task name
    client: str = ""              # client name from harvest ("" if absent)


# A lowercased project name -> ProjectInfo. Empty dict means "validation
# disabled" (e.g. startup fetch failed) — every caller MUST treat an empty
# index as "skip validation, pass through".
ProjectIndex = dict[str, ProjectInfo]


def build_project_index() -> ProjectIndex:
    """Fetch projects + tasks from harvest and build a lookup index.

    Calls `harvest list projects --json` exactly once. The harvest CLI returns
    a top-level JSON array of ProjectAssignment objects, each with a nested
    `project`, a nested `client`, and an array of `task_assignments` whose own
    `task` carries the name we want. We capture the client name too so the
    prompt can show which client each project belongs to — the model needs it
    to resolve requests phrased by client name (e.g. "log under Concepts NREC"
    when the project is "AI Platform"). We include both active and inactive task
    assignments — the tool's only job is to reject truly nonexistent names.

    On any failure (CLI error, malformed JSON, missing fields), returns an
    empty dict and prints a one-line warning. Callers MUST treat an empty
    index as "validation disabled, pass through".
    """
    result = harvest_cli.run(["list", "projects", "--json"])
    if not result["ok"]:
        print(
            f"warning: could not fetch project list ({result['stderr'].strip()}); "
            "project/task validation disabled this session.",
            file=sys.stderr,
        )
        return {}

    try:
        payload = json.loads(result["stdout"])
    except json.JSONDecodeError as e:
        print(
            f"warning: project list was not valid JSON ({e}); "
            "project/task validation disabled this session.",
            file=sys.stderr,
        )
        return {}

    if not isinstance(payload, list):
        return {}

    index: ProjectIndex = {}
    for assignment in payload:
        if not isinstance(assignment, dict):
            continue
        project = assignment.get("project") or {}
        if not isinstance(project, dict):
            continue
        name = project.get("name")
        if not isinstance(name, str) or not name:
            continue

        tasks: dict[str, str] = {}
        for task_assignment in assignment.get("task_assignments") or []:
            if not isinstance(task_assignment, dict):
                continue
            task = task_assignment.get("task") or {}
            if not isinstance(task, dict):
                continue
            task_name = task.get("name")
            if isinstance(task_name, str) and task_name:
                tasks[task_name.lower()] = task_name

        client_obj = assignment.get("client")
        client_name = ""
        if isinstance(client_obj, dict):
            name_val = client_obj.get("name")
            if isinstance(name_val, str):
                client_name = name_val

        index[name.lower()] = ProjectInfo(
            canonical_name=name, tasks=tasks, client=client_name
        )

    return index
