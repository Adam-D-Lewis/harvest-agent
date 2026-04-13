"""Canned harvest_cli.run responses for eval cases.

Evals mock the harvest CLI so runs are deterministic and don't touch any real
Harvest account. A HarvestFixture routes each subcommand to a canned response
(empty today, a specific entry, a week's worth, etc.). Selection happens via
the fixture name on each eval Case.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch


@dataclass
class HarvestFixture:
    """A canned harvest_cli.run implementation.

    The `run` method inspects the first few positional args (same shape as a
    real `harvest <subcmd> ...` invocation) and returns the matching canned
    payload as `{"ok": True, "returncode": 0, "stdout": ..., "stderr": ""}`.
    """

    name: str
    today_entries: list[dict] = field(default_factory=list)
    range_entries: list[dict] = field(default_factory=list)
    status_text: str = "25.5h/36h (71%)"
    projects_text: str = "Web Redesign\nMobile App v2\nPTO\nAdmin\n"
    tasks_text: str = "Programming\nMeetings / Standups\n"
    projects_json: str = ""    # populated in __post_init__ if empty
    tasks_json: str = ""

    def __post_init__(self):
        if not self.projects_json:
            self.projects_json = json.dumps([
                {
                    "id": 100,
                    "is_active": True,
                    "project": {"id": 1, "name": "Web Redesign", "code": ""},
                    "client": {"id": 1, "name": "Acme Corp"},
                    "task_assignments": [
                        {"id": 9001, "is_active": True, "task": {"id": 10, "name": "Programming"}},
                        {"id": 9002, "is_active": True, "task": {"id": 11, "name": "Meetings / Standups"}},
                    ],
                },
                {
                    "id": 101,
                    "is_active": True,
                    "project": {"id": 2, "name": "Mobile App v2", "code": ""},
                    "client": {"id": 2, "name": "Globex Inc"},
                    "task_assignments": [
                        {"id": 9003, "is_active": True, "task": {"id": 20, "name": "Backend API"}},
                        {"id": 9004, "is_active": True, "task": {"id": 21, "name": "Meetings / Standups"}},
                    ],
                },
                {
                    "id": 102,
                    "is_active": True,
                    "project": {"id": 3, "name": "PTO (PTO, Sick Leave, Parental Leave)", "code": ""},
                    "client": {"id": 1, "name": "Initech"},
                    "task_assignments": [
                        {"id": 9005, "is_active": True, "task": {"id": 30, "name": "PTO"}},
                    ],
                },
                {
                    "id": 103,
                    "is_active": True,
                    "project": {"id": 4, "name": "Admin", "code": ""},
                    "client": {"id": 1, "name": "Initech"},
                    "task_assignments": [
                        {"id": 9006, "is_active": True, "task": {"id": 40, "name": "Misc"}},
                    ],
                },
            ])
        if not self.tasks_json:
            self.tasks_json = "[]"

    def run(self, args: list[str], timeout: int = 30) -> dict[str, Any]:
        cmd = args[0] if args else ""
        if cmd == "view":
            if len(args) >= 2 and args[1] == "today":
                # Harvest returns `null` (not `[]`) when no entries exist.
                body = json.dumps(self.today_entries) if self.today_entries else "null"
                return _ok(body)
            if len(args) >= 2 and args[1] == "week":
                body = json.dumps(self.range_entries) if self.range_entries else "null"
                return _ok(body)
            if "--from" in args:
                body = json.dumps(self.range_entries) if self.range_entries else "null"
                return _ok(body)
            return _ok("null")
        if cmd == "status":
            return _ok(self.status_text)
        if cmd == "list":
            if len(args) >= 2 and args[1] == "projects":
                if "--json" in args:
                    return _ok(self.projects_json)
                return _ok(self.projects_text)
            if len(args) >= 2 and args[1] == "tasks":
                if "--json" in args:
                    return _ok(self.tasks_json)
                return _ok(self.tasks_text)
            return _ok("")
        if cmd == "log":
            return _ok("Logged entry")
        if cmd == "start":
            return _ok("Timer started")
        if cmd == "stop":
            return _ok("Timer stopped")
        if cmd == "edit":
            return _ok("Entry updated")
        if cmd == "delete":
            return _ok("Entry deleted")
        return _ok("")


def _ok(stdout: str) -> dict[str, Any]:
    return {"ok": True, "returncode": 0, "stdout": stdout, "stderr": ""}


# ---------- Predefined fixtures ----------

EMPTY = HarvestFixture(name="empty")

ENTRY_99 = HarvestFixture(
    name="entry_99",
    today_entries=[
        {
            "id": 99,
            "spent_date": "2026-04-08",
            "hours": 4.5,
            "notes": "old notes",
            "is_locked": False,
            "is_running": False,
            "billable": True,
            "project": {"id": 1, "name": "Web Redesign", "code": "AC-001"},
            "task": {"id": 2, "name": "Programming"},
            "client": {"id": 3, "name": "Acme Corp"},
        },
    ],
)

MULTIPLE_ENTRIES = HarvestFixture(
    name="multiple_entries",
    today_entries=[
        {
            "id": 101,
            "spent_date": "2026-04-08",
            "hours": 2.0,
            "notes": "standup",
            "is_locked": False,
            "is_running": False,
            "billable": True,
            "project": {"id": 1, "name": "Web Redesign", "code": "AC-001"},
            "task": {"id": 5, "name": "Meetings / Standups"},
            "client": {"id": 3, "name": "Acme Corp"},
        },
        {
            "id": 102,
            "spent_date": "2026-04-08",
            "hours": 3.5,
            "notes": "feature work",
            "is_locked": False,
            "is_running": False,
            "billable": True,
            "project": {"id": 1, "name": "Web Redesign", "code": "AC-001"},
            "task": {"id": 2, "name": "Programming"},
            "client": {"id": 3, "name": "Acme Corp"},
        },
    ],
)


FIXTURES: dict[str, HarvestFixture] = {
    f.name: f for f in [EMPTY, ENTRY_99, MULTIPLE_ENTRIES]
}


@contextmanager
def patched_harvest(fixture: HarvestFixture):
    """Swap harvest_cli.run (as imported in tools.py) for the fixture's run."""
    with patch("harvest_agent.tools.harvest_cli.run", side_effect=fixture.run):
        yield


@contextmanager
def patched_confirm(accept: bool):
    """Force the confirmation prompt to return True or False without reading stdin."""
    with patch("harvest_agent.tools.confirm.confirm_action", return_value=accept):
        yield
