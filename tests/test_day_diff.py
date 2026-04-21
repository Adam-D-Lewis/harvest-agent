import json
from unittest.mock import patch

from harvest_agent.day_diff import fetch_today_entries, format_changes


def _entry(entry_id, hours=1.0, notes="", project="Admin", task="Misc"):
    return {
        "id": entry_id,
        "spent_date": "2026-04-20",
        "hours": hours,
        "notes": notes,
        "project": {"id": 1, "name": project, "code": ""},
        "task": {"id": 2, "name": task},
    }


def _view_response(entries):
    payload = json.dumps(entries) if entries else "null"
    return {"ok": True, "returncode": 0, "stdout": payload, "stderr": ""}


# ---- fetch_today_entries ----


def test_fetch_today_entries_returns_list_for_populated_day():
    with patch("harvest_agent.day_diff.harvest_cli.run", return_value=_view_response([_entry(1), _entry(2)])) as m:
        entries = fetch_today_entries()
    m.assert_called_once_with(["view", "today", "--json"])
    assert len(entries) == 2
    assert entries[0]["id"] == 1


def test_fetch_today_entries_empty_on_null_payload():
    with patch("harvest_agent.day_diff.harvest_cli.run", return_value=_view_response(None)):
        assert fetch_today_entries() == []


def test_fetch_today_entries_empty_on_cli_failure():
    failed = {"ok": False, "returncode": 1, "stdout": "", "stderr": "auth"}
    with patch("harvest_agent.day_diff.harvest_cli.run", return_value=failed):
        assert fetch_today_entries() == []


def test_fetch_today_entries_empty_on_malformed_json():
    bad = {"ok": True, "returncode": 0, "stdout": "not json", "stderr": ""}
    with patch("harvest_agent.day_diff.harvest_cli.run", return_value=bad):
        assert fetch_today_entries() == []


# ---- format_changes: no-op cases ----


def test_format_changes_empty_string_when_nothing_changed():
    entries = [_entry(1), _entry(2)]
    assert format_changes(entries, entries) == ""


def test_format_changes_empty_string_when_both_sides_empty():
    assert format_changes([], []) == ""


# ---- format_changes: detects changes ----


def test_format_changes_shows_added_entry():
    before: list = []
    after = [_entry(10, hours=1.5, project="Admin", task="People Management", notes="mentoring")]
    out = format_changes(before, after)
    assert "Changes this turn:" in out
    assert "+ Added:" in out
    assert "Admin / People Management" in out
    assert "1.5h" in out
    assert "mentoring" in out
    assert "Total: 0h → 1.5h" in out


def test_format_changes_shows_deleted_entry():
    before = [_entry(10, hours=1.0, project="Admin", task="Misc")]
    after: list = []
    out = format_changes(before, after)
    assert "- Deleted:" in out
    assert "Admin / Misc" in out
    assert "Total: 1.0h → 0h" in out


def test_format_changes_shows_modified_entry_by_id():
    before = [_entry(10, hours=0.5, notes="first")]
    after = [_entry(10, hours=1.0, notes="first")]
    out = format_changes(before, after)
    assert "~ Entry 10:" in out
    assert "hours" in out
    assert "0.5" in out and "1.0" in out


def test_format_changes_modified_shows_multiple_field_changes():
    before = [_entry(10, hours=0.5, notes="old", project="Admin", task="Misc")]
    after = [_entry(10, hours=1.0, notes="new", project="Admin", task="Recruiting")]
    out = format_changes(before, after)
    assert "~ Entry 10:" in out
    assert "hours" in out
    assert "task" in out
    assert "notes" in out


def test_format_changes_mixed_add_remove_modify():
    before = [_entry(1, hours=1.0), _entry(2, hours=1.0)]
    after = [_entry(1, hours=1.5), _entry(3, hours=2.0)]
    out = format_changes(before, after)
    assert "+ Added:" in out   # entry 3
    assert "- Deleted:" in out  # entry 2
    assert "~ Entry 1:" in out  # hours change
    # Total: 2.0 → 3.5
    assert "Total: 2.0h → 3.5h" in out


def test_format_changes_no_total_line_when_hours_unchanged():
    """A pure notes/project swap keeping total hours the same shouldn't add a redundant Total line."""
    before = [_entry(1, hours=1.0, notes="old")]
    after = [_entry(1, hours=1.0, notes="new")]
    out = format_changes(before, after)
    assert "~ Entry 1:" in out
    assert "Total:" not in out
