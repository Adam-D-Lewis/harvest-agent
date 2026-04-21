import json
from datetime import date
from unittest.mock import patch

from harvest_agent.recent_usage import build_recent_pairs


def _view_response(entries):
    """Fake `harvest view --json` response in the shape the CLI produces."""
    payload = json.dumps(entries) if entries else "null"
    return {"ok": True, "returncode": 0, "stdout": payload, "stderr": ""}


def _entry(project_name, task_name):
    return {
        "id": 1,
        "spent_date": "2026-04-01",
        "hours": 1.0,
        "notes": "",
        "project": {"id": 1, "name": project_name, "code": ""},
        "task": {"id": 2, "name": task_name},
    }


def test_build_recent_pairs_passes_correct_date_range():
    today = date(2026, 4, 20)
    with patch("harvest_agent.recent_usage.harvest_cli.run", return_value=_view_response([])) as m:
        build_recent_pairs(window_days=30, today=today)
    m.assert_called_once_with([
        "view", "--from", "2026-03-21", "--to", "2026-04-20", "--json",
    ])


def test_build_recent_pairs_collects_lowercased_pairs():
    today = date(2026, 4, 20)
    entries = [
        _entry("Admin", "People Management"),
        _entry("Deep Learning", "Programming"),
        _entry("Admin", "People Management"),  # duplicate — set dedupes
    ]
    with patch("harvest_agent.recent_usage.harvest_cli.run", return_value=_view_response(entries)):
        pairs = build_recent_pairs(window_days=30, today=today)
    assert pairs == {
        ("admin", "people management"),
        ("deep learning", "programming"),
    }


def test_build_recent_pairs_empty_on_null_response():
    """harvest returns `null` when the view range has no entries."""
    today = date(2026, 4, 20)
    with patch("harvest_agent.recent_usage.harvest_cli.run", return_value=_view_response(None)):
        pairs = build_recent_pairs(window_days=30, today=today)
    assert pairs == set()


def test_build_recent_pairs_empty_on_cli_failure():
    today = date(2026, 4, 20)
    failed = {"ok": False, "returncode": 1, "stdout": "", "stderr": "auth error"}
    with patch("harvest_agent.recent_usage.harvest_cli.run", return_value=failed):
        pairs = build_recent_pairs(window_days=30, today=today)
    assert pairs == set()


def test_build_recent_pairs_empty_on_malformed_json():
    today = date(2026, 4, 20)
    bad = {"ok": True, "returncode": 0, "stdout": "not json at all", "stderr": ""}
    with patch("harvest_agent.recent_usage.harvest_cli.run", return_value=bad):
        pairs = build_recent_pairs(window_days=30, today=today)
    assert pairs == set()


def test_build_recent_pairs_skips_entries_missing_project_or_task():
    today = date(2026, 4, 20)
    entries = [
        {"id": 1, "project": {"name": "Admin"}, "task": {"name": "Misc"}},
        {"id": 2, "project": None, "task": {"name": "Misc"}},        # skipped
        {"id": 3, "project": {"name": "X"}, "task": None},            # skipped
        {"id": 4, "project": {"name": ""}, "task": {"name": "Y"}},    # skipped (empty name)
    ]
    with patch("harvest_agent.recent_usage.harvest_cli.run", return_value=_view_response(entries)):
        pairs = build_recent_pairs(window_days=30, today=today)
    assert pairs == {("admin", "misc")}
