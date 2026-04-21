import json
from datetime import date
from unittest.mock import patch

from harvest_agent.day_diff import fetch_recent_entries, format_changes


def _entry(entry_id, hours=1.0, notes="", project="Admin", task="Misc", spent_date="2026-04-20"):
    return {
        "id": entry_id,
        "spent_date": spent_date,
        "hours": hours,
        "notes": notes,
        "project": {"id": 1, "name": project, "code": ""},
        "task": {"id": 2, "name": task},
    }


def _view_response(entries):
    payload = json.dumps(entries) if entries else "null"
    return {"ok": True, "returncode": 0, "stdout": payload, "stderr": ""}


# ---- fetch_recent_entries ----


def test_fetch_recent_entries_uses_today_window():
    today = date(2026, 4, 20)
    with patch("harvest_agent.day_diff.harvest_cli.run", return_value=_view_response([_entry(1)])) as m:
        entries = fetch_recent_entries(today)
    # 30 days back through 90 days forward.
    m.assert_called_once_with([
        "view", "--from", "2026-03-21", "--to", "2026-07-19", "--json",
    ])
    assert len(entries) == 1


def test_fetch_recent_entries_empty_on_null_payload():
    with patch("harvest_agent.day_diff.harvest_cli.run", return_value=_view_response(None)):
        assert fetch_recent_entries(date(2026, 4, 20)) == []


def test_fetch_recent_entries_empty_on_cli_failure():
    failed = {"ok": False, "returncode": 1, "stdout": "", "stderr": "auth"}
    with patch("harvest_agent.day_diff.harvest_cli.run", return_value=failed):
        assert fetch_recent_entries(date(2026, 4, 20)) == []


def test_fetch_recent_entries_empty_on_malformed_json():
    bad = {"ok": True, "returncode": 0, "stdout": "not json", "stderr": ""}
    with patch("harvest_agent.day_diff.harvest_cli.run", return_value=bad):
        assert fetch_recent_entries(date(2026, 4, 20)) == []


# ---- format_changes: no-op cases ----


def test_format_changes_empty_string_when_nothing_changed():
    entries = [_entry(1), _entry(2)]
    assert format_changes(entries, entries) == ""


def test_format_changes_empty_string_when_both_sides_empty():
    assert format_changes([], []) == ""


# ---- format_changes: single-day changes ----


def test_format_changes_groups_under_date_header_for_added_entry():
    before: list = []
    after = [_entry(10, hours=1.5, project="Admin", task="People Management", notes="mentoring")]
    out = format_changes(before, after)
    assert "Changes this turn:" in out
    assert "  2026-04-20:" in out
    assert "+ Added:" in out
    assert "Admin / People Management" in out
    assert "1.5h" in out
    assert "mentoring" in out
    assert "Total: 0h → 1.5h" in out


def test_format_changes_shows_deleted_entry_under_its_date():
    before = [_entry(10, hours=1.0, project="Admin", task="Misc")]
    after: list = []
    out = format_changes(before, after)
    assert "  2026-04-20:" in out
    assert "- Deleted:" in out
    assert "Admin / Misc" in out
    assert "Total: 1.0h → 0h" in out


def test_format_changes_shows_modified_entry_by_id():
    before = [_entry(10, hours=0.5, notes="first")]
    after = [_entry(10, hours=1.0, notes="first")]
    out = format_changes(before, after)
    assert "  2026-04-20:" in out
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


def test_format_changes_no_total_line_when_hours_unchanged():
    """A pure notes/project swap keeping total hours the same shouldn't add a redundant Total line."""
    before = [_entry(1, hours=1.0, notes="old")]
    after = [_entry(1, hours=1.0, notes="new")]
    out = format_changes(before, after)
    assert "~ Entry 1:" in out
    assert "Total:" not in out


# ---- format_changes: multi-day changes ----


def test_format_changes_groups_changes_from_multiple_dates():
    """Editing yesterday while also logging today produces two date headers."""
    before = [
        _entry(1, hours=1.0, spent_date="2026-04-18"),
        _entry(2, hours=2.0, spent_date="2026-04-18"),
    ]
    after = [
        _entry(1, hours=1.5, spent_date="2026-04-18"),   # modified
        _entry(3, hours=0.5, spent_date="2026-04-20"),   # added
    ]
    out = format_changes(before, after)
    assert "  2026-04-20:" in out
    assert "  2026-04-18:" in out
    # 2026-04-20 should appear before 2026-04-18 (most-recent-first).
    assert out.index("2026-04-20:") < out.index("2026-04-18:")
    # Per-date totals, each only if that date's total changed.
    # 2026-04-18: was 3.0h (1.0 + 2.0), now 1.5h (only entry 1, entry 2 was deleted)
    assert "Total: 3.0h → 1.5h" in out
    # 2026-04-20: was 0h, now 0.5h
    assert "Total: 0h → 0.5h" in out


def test_format_changes_mixed_add_remove_modify_same_day():
    before = [_entry(1, hours=1.0), _entry(2, hours=1.0)]
    after = [_entry(1, hours=1.5), _entry(3, hours=2.0)]
    out = format_changes(before, after)
    # Single date, still grouped under its header.
    assert "  2026-04-20:" in out
    assert "+ Added:" in out   # entry 3
    assert "- Deleted:" in out  # entry 2
    assert "~ Entry 1:" in out  # hours change
    assert "Total: 2.0h → 3.5h" in out
