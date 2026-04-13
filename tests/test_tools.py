import json
from datetime import date
from unittest.mock import patch

import pytest

from harvest_agent import tools
from harvest_agent.config import Shortcut
from harvest_agent.project_index import ProjectInfo


def _ok(stdout="ok"):
    return {"ok": True, "returncode": 0, "stdout": stdout, "stderr": ""}


def _harvest_view_json(entries):
    """Build a fake `harvest view --json` response.

    The harvest CLI returns a top-level JSON array of entries (or `null` when
    empty). Each entry has nested project/task objects. This helper builds
    that exact shape.
    """
    payload = json.dumps(entries) if entries else "null"
    return {"ok": True, "returncode": 0, "stdout": payload, "stderr": ""}


def _entry(entry_id, hours=4.5, notes="standup", project_name="P", task_name="T"):
    """Build a fake entry in the shape harvest CLI actually returns."""
    return {
        "id": entry_id,
        "spent_date": "2026-04-06",
        "hours": hours,
        "notes": notes,
        "billable": True,
        "is_running": False,
        "is_locked": False,
        "project": {"id": 1, "name": project_name, "code": ""},
        "task": {"id": 2, "name": task_name},
        "client": {"id": 3, "name": "C"},
    }


def test_view_today_calls_harvest_view_today_json():
    with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok('{"entries": []}')) as m:
        result = tools.view_today()
    m.assert_called_once_with(["view", "today", "--json"])
    assert result["ok"] is True


def test_view_week_default_offset():
    with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok()) as m:
        tools.view_week()
    m.assert_called_once_with(["view", "week", "--json"])


def test_view_week_with_offset():
    with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok()) as m:
        tools.view_week(offset=-2)
    m.assert_called_once_with(["view", "week", "-2", "--json"])


def test_view_range():
    with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok()) as m:
        tools.view_range("2026-04-01", "2026-04-07")
    m.assert_called_once_with(["view", "--from", "2026-04-01", "--to", "2026-04-07", "--json"])


def test_list_projects():
    with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok()) as m:
        tools.list_projects()
    m.assert_called_once_with(["list", "projects"])


def test_list_tasks():
    with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok()) as m:
        tools.list_tasks(project_id=12345)
    m.assert_called_once_with(["list", "tasks", "-p", "12345"])


def test_status():
    with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok()) as m:
        tools.status()
    m.assert_called_once_with(["status"])


def test_log_time():
    with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok()) as m:
        tools.log_time(project="Web Redesign", task="Programming", hours=4.5, notes="standup", date="2026-04-07")
    m.assert_called_once_with(
        ["log", "Web Redesign", "Programming", "4.5", "standup", "--date", "2026-04-07"]
    )


def test_round_to_quarter():
    assert tools._round_to_quarter(2.67) == 2.75
    assert tools._round_to_quarter(5.1) == 5.0
    assert tools._round_to_quarter(1.3) == 1.25
    assert tools._round_to_quarter(3.9) == 4.0
    assert tools._round_to_quarter(4.5) == 4.5  # already a quarter — no change
    assert tools._round_to_quarter(0.0) == 0.0


def test_log_time_rounds_hours_to_nearest_quarter():
    """The LLM should pass raw values — tools round to 0.25 deterministically."""
    with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok()) as m:
        tools.log_time(project="P", task="T", hours=5.1, notes="", date="2026-04-07")
    # 5.1 should have been rounded to 5.0 before the CLI call
    m.assert_called_once_with(["log", "P", "T", "5.0", "", "--date", "2026-04-07"])


def test_log_time_adds_rounding_note_when_value_changes():
    with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok()) as m:
        result = tools.log_time(project="P", task="T", hours=2.67, notes="", date="2026-04-07")
    m.assert_called_once_with(["log", "P", "T", "2.75", "", "--date", "2026-04-07"])
    assert "tool_notes" in result
    notes_text = " ".join(result["tool_notes"])
    assert "2.67" in notes_text
    assert "2.75" in notes_text


def test_log_time_no_tool_notes_when_nothing_auto_processed():
    with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok()) as m:
        result = tools.log_time(project="P", task="T", hours=4.5, notes="", date="2026-04-07")
    m.assert_called_once_with(["log", "P", "T", "4.5", "", "--date", "2026-04-07"])
    assert "tool_notes" not in result


def test_log_time_empty_notes_still_passes_arg():
    with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok()) as m:
        tools.log_time(project="P", task="T", hours=1.0, notes="", date="2026-04-07")
    # Empty notes still passed as "" so the CLI doesn't drop into TTY prompt mode
    m.assert_called_once_with(["log", "P", "T", "1.0", "", "--date", "2026-04-07"])


def test_start_timer():
    with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok()) as m:
        tools.start_timer(project="P", task="T", notes="working")
    m.assert_called_once_with(["start", "P", "T", "working"])


def test_start_timer_empty_notes():
    with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok()) as m:
        tools.start_timer(project="P", task="T", notes="")
    m.assert_called_once_with(["start", "P", "T", ""])


def test_stop_timer():
    with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok()) as m:
        tools.stop_timer()
    m.assert_called_once_with(["stop"])


def test_parse_entries_handles_null_payload():
    """harvest view --json returns `null` when there are no entries."""
    assert tools._parse_entries("null") == []


def test_parse_entries_handles_top_level_array():
    payload = json.dumps([_entry(1), _entry(2)])
    result = tools._parse_entries(payload)
    assert len(result) == 2
    assert result[0]["id"] == 1


def test_parse_entries_handles_invalid_json():
    assert tools._parse_entries("not json {{") == []


def test_summarize_entry_flattens_nested_project_and_task():
    summary = tools._summarize_entry(_entry(99, hours=2.0, project_name="Web Redesign", task_name="Programming"))
    assert summary["id"] == 99
    assert summary["hours"] == 2.0
    assert summary["project"] == "Web Redesign"
    assert summary["task"] == "Programming"
    assert summary["date"] == "2026-04-06"


def test_edit_entry_confirmed_runs_cli():
    fake_today = _harvest_view_json([_entry(99)])
    fake_edit = _ok()
    with patch("harvest_agent.tools.harvest_cli.run", side_effect=[fake_today, fake_edit]) as m, \
         patch("harvest_agent.tools.confirm.confirm_action", return_value=True) as c:
        result = tools.edit_entry(entry_id=99, hours=2.5)

    assert result["ok"] is True
    # First call: view to fetch current state. Second call: edit.
    assert m.call_args_list[0].args[0][0] == "view"
    assert m.call_args_list[1].args[0] == ["edit", "--id", "99", "--hours", "2.5"]
    c.assert_called_once()


def test_edit_entry_passes_summarized_before_dict_to_confirm():
    """The `before` dict shown to the user must be the flattened summary, not the raw nested entry."""
    fake_today = _harvest_view_json([_entry(99, hours=4.5, project_name="Web Redesign", task_name="Programming")])
    with patch("harvest_agent.tools.harvest_cli.run", side_effect=[fake_today, _ok()]), \
         patch("harvest_agent.tools.confirm.confirm_action", return_value=True) as c:
        tools.edit_entry(entry_id=99, hours=2.5)
    title, before, after = c.call_args.args
    assert before["project"] == "Web Redesign"  # flattened, not {"id": ..., "name": ...}
    assert before["task"] == "Programming"
    assert before["hours"] == 4.5
    assert after["hours"] == 2.5
    assert after["project"] == "Web Redesign"  # unchanged fields preserved


def test_edit_entry_declined_does_not_run_cli():
    fake_today = _harvest_view_json([_entry(99)])
    with patch("harvest_agent.tools.harvest_cli.run", side_effect=[fake_today]) as m, \
         patch("harvest_agent.tools.confirm.confirm_action", return_value=False):
        result = tools.edit_entry(entry_id=99, hours=2.5)

    assert result["ok"] is False
    assert "cancelled" in result["stderr"]
    # Only the view call happened, not the edit
    assert len(m.call_args_list) == 1


def test_edit_entry_passes_only_provided_fields():
    fake_today = _harvest_view_json([_entry(1, hours=1.0, notes="x")])
    with patch("harvest_agent.tools.harvest_cli.run", side_effect=[fake_today, _ok()]) as m, \
         patch("harvest_agent.tools.confirm.confirm_action", return_value=True):
        tools.edit_entry(entry_id=1, notes="updated")
    assert m.call_args_list[1].args[0] == ["edit", "--id", "1", "--notes", "updated"]


def test_delete_entry_confirmed_runs_cli():
    fake_today = _harvest_view_json([_entry(7, hours=1.0, notes="x")])
    with patch("harvest_agent.tools.harvest_cli.run", side_effect=[fake_today, _ok()]) as m, \
         patch("harvest_agent.tools.confirm.confirm_action", return_value=True):
        result = tools.delete_entry(entry_id=7)
    assert result["ok"] is True
    assert m.call_args_list[1].args[0] == ["delete", "--id", "7"]


def test_delete_entry_declined():
    fake_today = _harvest_view_json([_entry(7, hours=1.0, notes="x")])
    with patch("harvest_agent.tools.harvest_cli.run", side_effect=[fake_today]) as m, \
         patch("harvest_agent.tools.confirm.confirm_action", return_value=False):
        result = tools.delete_entry(entry_id=7)
    assert result["ok"] is False
    assert len(m.call_args_list) == 1


def test_edit_entry_lookup_uses_single_window_call():
    """The lookup is one view call over a -30d/+90d window, then the edit."""
    tools.configure(today=date(2026, 4, 8))
    try:
        range_view = _harvest_view_json([_entry(99, hours=4.5, notes="old")])
        with patch("harvest_agent.tools.harvest_cli.run", side_effect=[range_view, _ok()]) as m, \
             patch("harvest_agent.tools.confirm.confirm_action", return_value=True):
            tools.edit_entry(entry_id=99, hours=2.5)
        # Calls: one view (range only) + one edit
        assert len(m.call_args_list) == 2
        assert m.call_args_list[0].args[0] == [
            "view", "--from", "2026-03-09", "--to", "2026-07-07", "--json"
        ]
        assert m.call_args_list[1].args[0] == ["edit", "--id", "99", "--hours", "2.5"]
    finally:
        tools.configure()


def test_edit_entry_rounds_hours_to_quarter():
    """edit_entry should also round hours to the nearest 0.25."""
    fake_today = _harvest_view_json([_entry(99, hours=4.5)])
    with patch("harvest_agent.tools.harvest_cli.run", side_effect=[fake_today, _ok()]) as m, \
         patch("harvest_agent.tools.confirm.confirm_action", return_value=True) as c:
        result = tools.edit_entry(entry_id=99, hours=5.1)

    # CLI call uses rounded value
    assert m.call_args_list[1].args[0] == ["edit", "--id", "99", "--hours", "5.0"]
    # Diff shown to the user also uses the rounded value
    _, _, after = c.call_args.args
    assert after["hours"] == 5.0
    # Return value has tool notes mentioning the rounding
    assert "tool_notes" in result
    assert any("5.1" in n and "5.0" in n for n in result["tool_notes"])


def test_edit_entry_no_hours_no_tool_notes():
    """When hours isn't passed, edit_entry should not touch anything hour-related."""
    fake_today = _harvest_view_json([_entry(1, hours=1.0, notes="x")])
    with patch("harvest_agent.tools.harvest_cli.run", side_effect=[fake_today, _ok()]) as m, \
         patch("harvest_agent.tools.confirm.confirm_action", return_value=True):
        result = tools.edit_entry(entry_id=1, notes="updated")
    assert m.call_args_list[1].args[0] == ["edit", "--id", "1", "--notes", "updated"]
    assert "tool_notes" not in result


def test_edit_entry_id_not_found_anywhere_uses_placeholder_before():
    """If the entry can't be found in the window, still show a confirmation with a placeholder."""
    empty = _harvest_view_json([])
    with patch("harvest_agent.tools.harvest_cli.run", side_effect=[empty, _ok()]), \
         patch("harvest_agent.tools.confirm.confirm_action", return_value=True) as c:
        tools.edit_entry(entry_id=42, hours=1.0)
    title, before, after = c.call_args.args
    assert before["id"] == 42
    assert before["note"] == "entry not found in -30d/+90d window"


def test_find_entry_locates_future_dated_entry():
    """_find_entry must find entries dated in the future (PTO planning).

    Regression: PTO entries logged ahead of time were dated in the future and
    fell outside the old "today + last 14 days" window, so the delete
    confirmation showed only the entry ID and an "entry not found" placeholder.

    The mock returns the future entry only when the requested view range
    actually includes its date. That way, the OLD lookup (which only searches
    backwards from today) will MISS the entry, while the NEW lookup (which
    extends forward) will FIND it.
    """
    tools.configure(today=date(2026, 4, 8))
    try:
        future_entry = _entry(
            99,
            hours=8.0,
            notes="Out of office",
            project_name="PTO (PTO, Sick Leave, Parental Leave)",
            task_name="PTO",
        )
        future_entry["spent_date"] = "2026-05-08"  # 30 days in the future
        entry_date = date(2026, 5, 8)

        def mock_harvest_run(args, timeout=30):
            if args[:2] == ["view", "today"]:
                return _harvest_view_json([])  # today is empty
            if args[0] == "view" and "--from" in args:
                from_d = date.fromisoformat(args[args.index("--from") + 1])
                to_d = date.fromisoformat(args[args.index("--to") + 1])
                if from_d <= entry_date <= to_d:
                    return _harvest_view_json([future_entry])
                return _harvest_view_json([])
            return _ok()

        with patch("harvest_agent.tools.harvest_cli.run", side_effect=mock_harvest_run), \
             patch("harvest_agent.tools.confirm.confirm_action", return_value=True) as c:
            tools.delete_entry(entry_id=99)
        title, before, after = c.call_args.args
        # Full summary should be present, not the placeholder
        assert before["id"] == 99
        assert before["date"] == "2026-05-08"
        assert before["hours"] == 8.0
        assert before["project"] == "PTO (PTO, Sick Leave, Parental Leave)"
        assert before["task"] == "PTO"
        assert "note" not in before  # the placeholder marker should not appear
        assert after is None  # delete: no after dict
    finally:
        tools.configure()


def test_find_entry_window_uses_correct_dates():
    """_find_entry searches a window: 30 days back, 90 days forward."""
    tools.configure(today=date(2026, 4, 8))
    try:
        with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok()) as m, \
             patch("harvest_agent.tools.confirm.confirm_action", return_value=True):
            tools.delete_entry(entry_id=99)
        # First call is the lookup. Verify the exact window.
        view_call = m.call_args_list[0].args[0]
        assert view_call == [
            "view", "--from", "2026-03-09", "--to", "2026-07-07", "--json"
        ]
    finally:
        tools.configure()


# ---------- Shortcut resolution ----------


@pytest.fixture
def configured_shortcuts():
    """Install a known shortcut table into tools module state for the test, then clear."""
    tools.configure(
        shortcuts=[
            Shortcut(name="acme", project="Web Redesign", task="Programming"),
            Shortcut(name="mobile meeting", project="Mobile App v2", task="Meetings / Standups"),
        ],
        today=date(2026, 4, 8),  # Wednesday, for the date-parsing tests
    )
    yield
    tools.configure()  # reset


def test_resolve_shortcut_returns_shortcut(configured_shortcuts):
    s = tools._resolve_shortcut("acme")
    assert s is not None
    assert s.project == "Web Redesign"
    assert s.task == "Programming"


def test_resolve_shortcut_returns_none_for_unknown():
    tools.configure()  # empty
    assert tools._resolve_shortcut("not a shortcut") is None


def test_log_time_resolves_shortcut_project(configured_shortcuts):
    with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok()) as m:
        tools.log_time(project="acme", task="", hours=1.0, notes="", date="today")
    # Project should be resolved from "acme" to "Web Redesign"
    args = m.call_args.args[0]
    assert args[1] == "Web Redesign"
    assert args[2] == "Programming"


def test_log_time_shortcut_keeps_llm_task_if_provided(configured_shortcuts):
    """If the LLM explicitly passes a task, the shortcut's task should NOT override it."""
    with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok()) as m:
        tools.log_time(
            project="acme", task="Meetings / Standups", hours=1.0, notes="", date="today"
        )
    args = m.call_args.args[0]
    assert args[1] == "Web Redesign"  # project resolved
    assert args[2] == "Meetings / Standups"  # LLM's task preserved


def test_log_time_non_shortcut_project_passes_through(configured_shortcuts):
    with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok()) as m:
        tools.log_time(
            project="Some Random Project", task="Some Task", hours=1.0, notes="", date="today"
        )
    args = m.call_args.args[0]
    assert args[1] == "Some Random Project"
    assert args[2] == "Some Task"


def test_log_time_tool_notes_mention_shortcut(configured_shortcuts):
    with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok()):
        result = tools.log_time(project="acme", task="", hours=1.0, notes="", date="today")
    assert "tool_notes" in result
    assert any("acme" in n for n in result["tool_notes"])


def test_edit_entry_resolves_shortcut_project(configured_shortcuts):
    fake_today = _harvest_view_json([_entry(1)])
    with patch("harvest_agent.tools.harvest_cli.run", side_effect=[fake_today, _ok()]) as m, \
         patch("harvest_agent.tools.confirm.confirm_action", return_value=True):
        tools.edit_entry(entry_id=1, project="acme")
    # The edit CLI call should get the resolved project AND task
    edit_args = m.call_args_list[1].args[0]
    assert "--project" in edit_args
    assert edit_args[edit_args.index("--project") + 1] == "Web Redesign"
    assert "--task" in edit_args
    assert edit_args[edit_args.index("--task") + 1] == "Programming"


# ---------- Date parsing ----------


def test_parse_date_iso_passthrough(configured_shortcuts):
    assert tools._parse_date("2026-05-15") == "2026-05-15"


def test_parse_date_today(configured_shortcuts):
    # today is 2026-04-08 (Wed) per the fixture
    assert tools._parse_date("today") == "2026-04-08"


def test_parse_date_yesterday(configured_shortcuts):
    assert tools._parse_date("yesterday") == "2026-04-07"


def test_parse_date_tomorrow(configured_shortcuts):
    assert tools._parse_date("tomorrow") == "2026-04-09"


def test_parse_date_this_friday(configured_shortcuts):
    # today is Wed 2026-04-08, "this Friday" -> upcoming Friday
    assert tools._parse_date("this Friday") == "2026-04-10"


def test_parse_date_case_insensitive(configured_shortcuts):
    assert tools._parse_date("YESTERDAY") == "2026-04-07"
    # "next <day>" is rejected regardless of casing — falls through to the
    # generic "Could not parse" branch.
    with pytest.raises(ValueError, match="Could not parse"):
        tools._parse_date("Next MONDAY")


def test_parse_date_bare_dayname(configured_shortcuts):
    # today is Wed; bare "Friday" -> upcoming Friday
    assert tools._parse_date("Friday") == "2026-04-10"


def test_parse_date_empty_is_today(configured_shortcuts):
    assert tools._parse_date("") == "2026-04-08"


def test_parse_date_invalid_raises(configured_shortcuts):
    with pytest.raises(ValueError, match="Could not parse"):
        tools._parse_date("sometime next week maybe")


def test_parse_date_next_dayname_rejected(configured_shortcuts):
    """next <day> is ambiguous in English; the parser must reject it."""
    with pytest.raises(ValueError, match="Could not parse"):
        tools._parse_date("next Thursday")


def test_parse_date_last_dayname_rejected(configured_shortcuts):
    """last <day> is ambiguous in English; the parser must reject it."""
    with pytest.raises(ValueError, match="Could not parse"):
        tools._parse_date("last Tuesday")


def test_log_time_parses_relative_date(configured_shortcuts):
    """log_time should delegate date parsing to _parse_date — verify with a
    surviving relative form ('this Friday' from Wed Apr 8 → Apr 10)."""
    with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok()) as m:
        tools.log_time(project="P", task="T", hours=1.0, notes="", date="this Friday")
    args = m.call_args.args[0]
    assert args[-1] == "2026-04-10"
    assert "--date" in args


def test_log_time_invalid_date_returns_error(configured_shortcuts):
    result = tools.log_time(project="P", task="T", hours=1.0, notes="", date="whenever")
    assert result["ok"] is False
    assert "whenever" in result["stderr"]


def test_log_time_next_dayname_returns_error(configured_shortcuts):
    """log_time must surface the parser rejection and never invoke the CLI."""
    with patch("harvest_agent.tools.harvest_cli.run") as m:
        result = tools.log_time(
            project="P", task="T", hours=1.0, notes="", date="next Thursday"
        )
    assert result["ok"] is False
    assert "next Thursday" in result["stderr"]
    m.assert_not_called()


def test_log_time_last_dayname_returns_error(configured_shortcuts):
    with patch("harvest_agent.tools.harvest_cli.run") as m:
        result = tools.log_time(
            project="P", task="T", hours=1.0, notes="", date="last Tuesday"
        )
    assert result["ok"] is False
    assert "last Tuesday" in result["stderr"]
    m.assert_not_called()


def test_configure_stores_project_index():
    idx = {
        "web redesign": ProjectInfo(
            canonical_name="Web Redesign",
            tasks={"programming": "Programming"},
        ),
    }
    tools.configure(project_index=idx)
    try:
        assert tools._context.project_index == idx
    finally:
        tools.configure()  # reset


def test_configure_default_project_index_is_empty():
    tools.configure()
    assert tools._context.project_index == {}


def test_validate_project_task_passes_through_when_index_empty():
    tools.configure()  # empty index
    result = tools._validate_project_task("Anything", "Whatever")
    assert result == ("Anything", "Whatever")


def test_validate_project_task_passes_through_empty_task_when_index_empty():
    tools.configure()
    result = tools._validate_project_task("X", "")
    assert result == ("X", "")


@pytest.fixture
def configured_project_index():
    """Install a small known project index for validation tests."""
    tools.configure(
        project_index={
            "web redesign": ProjectInfo(
                canonical_name="Web Redesign",
                tasks={"programming": "Programming", "meetings / standups": "Meetings / Standups"},
            ),
            "mobile app v2": ProjectInfo(
                canonical_name="Mobile App v2",
                tasks={"backend api": "Backend API"},
            ),
            "admin": ProjectInfo(canonical_name="Admin", tasks={"misc": "Misc"}),
        },
    )
    yield
    tools.configure()


def test_validate_project_task_canonicalizes_case(configured_project_index):
    result = tools._validate_project_task("web redesign", "")
    assert result == ("Web Redesign", "")


def test_validate_project_task_canonicalizes_mixed_case(configured_project_index):
    result = tools._validate_project_task("WEB Redesign", "")
    assert result == ("Web Redesign", "")


def test_validate_project_task_unknown_project_returns_error(configured_project_index):
    result = tools._validate_project_task("Imaginary Project", "")
    assert isinstance(result, str)
    assert "Imaginary Project" in result
    assert "doesn't exist" in result
    # Valid project list is included
    assert "Web Redesign" in result
    assert "Mobile App v2" in result
    assert "Admin" in result


def test_validate_project_task_unknown_project_includes_did_you_mean(configured_project_index):
    # "Web Rdesign" is one letter off — difflib should catch it
    result = tools._validate_project_task("Web Rdesign", "")
    assert isinstance(result, str)
    assert "Did you mean" in result
    assert "Web Redesign" in result


def test_validate_project_task_unknown_project_no_close_match_omits_did_you_mean(configured_project_index):
    # Wildly different name — no close match
    result = tools._validate_project_task("Quantum Banana Republic", "")
    assert isinstance(result, str)
    assert "Did you mean" not in result


def test_validate_project_task_canonicalizes_task_case(configured_project_index):
    result = tools._validate_project_task("Web Redesign", "PROGRAMMING")
    assert result == ("Web Redesign", "Programming")


def test_validate_project_task_empty_task_short_circuits(configured_project_index):
    result = tools._validate_project_task("Web Redesign", "")
    assert result == ("Web Redesign", "")


def test_validate_project_task_unknown_task_returns_error(configured_project_index):
    result = tools._validate_project_task("Web Redesign", "Imaginary Task")
    assert isinstance(result, str)
    assert "Imaginary Task" in result
    assert "Web Redesign" in result
    assert "doesn't exist" in result
    # Valid task list for that project is included
    assert "Programming" in result
    assert "Meetings / Standups" in result


def test_validate_project_task_unknown_task_includes_did_you_mean(configured_project_index):
    # "Programing" — single missing letter
    result = tools._validate_project_task("Web Redesign", "Programing")
    assert isinstance(result, str)
    assert "Did you mean" in result
    assert "Programming" in result


def test_log_time_rejects_unknown_project(configured_project_index):
    with patch("harvest_agent.tools.harvest_cli.run") as m:
        result = tools.log_time(
            project="Imaginary", task="", hours=1.0, notes="", date="2026-04-08"
        )
    assert result["ok"] is False
    assert "Imaginary" in result["stderr"]
    assert "doesn't exist" in result["stderr"]
    # CLI must NOT be called when validation fails
    m.assert_not_called()


def test_log_time_rejects_unknown_task_on_real_project(configured_project_index):
    with patch("harvest_agent.tools.harvest_cli.run") as m:
        result = tools.log_time(
            project="Web Redesign", task="Imaginary", hours=1.0, notes="", date="2026-04-08"
        )
    assert result["ok"] is False
    assert "Imaginary" in result["stderr"]
    assert "Web Redesign" in result["stderr"]
    m.assert_not_called()


def test_log_time_canonicalizes_project_and_task(configured_project_index):
    with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok()) as m:
        tools.log_time(
            project="web redesign", task="programming", hours=1.0, notes="", date="2026-04-08"
        )
    args = m.call_args.args[0]
    # CLI sees the canonical names, not the lowercased ones the model passed
    assert args[1] == "Web Redesign"
    assert args[2] == "Programming"


def test_log_time_validation_runs_after_shortcut_resolution(configured_project_index):
    """A shortcut whose resolved project doesn't exist must still be rejected."""
    tools.configure(
        shortcuts=[Shortcut(name="bogus", project="Imaginary", task="Whatever")],
        project_index=tools._context.project_index,
    )
    try:
        with patch("harvest_agent.tools.harvest_cli.run") as m:
            result = tools.log_time(
                project="bogus", task="", hours=1.0, notes="", date="2026-04-08"
            )
        assert result["ok"] is False
        assert "Imaginary" in result["stderr"]
        m.assert_not_called()
    finally:
        tools.configure()


def test_log_time_validation_disabled_when_index_empty():
    """Empty index = startup fetch failed = validation off, harvest still called."""
    tools.configure()  # empty index
    with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok()) as m:
        result = tools.log_time(
            project="anything goes", task="", hours=1.0, notes="", date="2026-04-08"
        )
    assert result["ok"] is True
    m.assert_called_once()


def test_start_timer_rejects_unknown_project(configured_project_index):
    with patch("harvest_agent.tools.harvest_cli.run") as m:
        result = tools.start_timer(project="Imaginary", task="Programming", notes="")
    assert result["ok"] is False
    assert "Imaginary" in result["stderr"]
    m.assert_not_called()


def test_start_timer_rejects_unknown_task(configured_project_index):
    with patch("harvest_agent.tools.harvest_cli.run") as m:
        result = tools.start_timer(project="Web Redesign", task="Imaginary", notes="")
    assert result["ok"] is False
    assert "Imaginary" in result["stderr"]
    m.assert_not_called()


def test_start_timer_canonicalizes_names(configured_project_index):
    with patch("harvest_agent.tools.harvest_cli.run", return_value=_ok()) as m:
        tools.start_timer(project="web redesign", task="programming", notes="")
    m.assert_called_once_with(["start", "Web Redesign", "Programming", ""])


def test_edit_entry_rejects_task_without_project():
    fake_today = _harvest_view_json([_entry(7)])
    with patch("harvest_agent.tools.harvest_cli.run", side_effect=[fake_today]) as m, \
         patch("harvest_agent.tools.confirm.confirm_action", return_value=True):
        result = tools.edit_entry(entry_id=7, task="Programming")
    assert result["ok"] is False
    assert "project" in result["stderr"].lower()
    # No edit CLI call
    edit_calls = [c for c in m.call_args_list if c.args[0][0] == "edit"]
    assert edit_calls == []


def test_edit_entry_rejects_unknown_project(configured_project_index):
    fake_today = _harvest_view_json([_entry(7)])
    with patch("harvest_agent.tools.harvest_cli.run", side_effect=[fake_today]) as m, \
         patch("harvest_agent.tools.confirm.confirm_action", return_value=True):
        result = tools.edit_entry(entry_id=7, project="Imaginary", task="Whatever")
    assert result["ok"] is False
    assert "Imaginary" in result["stderr"]
    edit_calls = [c for c in m.call_args_list if c.args[0][0] == "edit"]
    assert edit_calls == []


def test_edit_entry_rejects_unknown_task_on_real_project(configured_project_index):
    fake_today = _harvest_view_json([_entry(7)])
    with patch("harvest_agent.tools.harvest_cli.run", side_effect=[fake_today]) as m, \
         patch("harvest_agent.tools.confirm.confirm_action", return_value=True):
        result = tools.edit_entry(entry_id=7, project="Web Redesign", task="Imaginary")
    assert result["ok"] is False
    assert "Imaginary" in result["stderr"]
    edit_calls = [c for c in m.call_args_list if c.args[0][0] == "edit"]
    assert edit_calls == []


def test_edit_entry_canonicalizes_project_and_task(configured_project_index):
    fake_today = _harvest_view_json([_entry(7)])
    with patch("harvest_agent.tools.harvest_cli.run", side_effect=[fake_today, _ok()]) as m, \
         patch("harvest_agent.tools.confirm.confirm_action", return_value=True):
        tools.edit_entry(entry_id=7, project="web redesign", task="programming")
    edit_args = m.call_args_list[1].args[0]
    assert edit_args[edit_args.index("--project") + 1] == "Web Redesign"
    assert edit_args[edit_args.index("--task") + 1] == "Programming"


def test_edit_entry_project_only_validates_alone(configured_project_index):
    """Passing only project should validate just the project (no task lookup)."""
    fake_today = _harvest_view_json([_entry(7)])
    with patch("harvest_agent.tools.harvest_cli.run", side_effect=[fake_today, _ok()]) as m, \
         patch("harvest_agent.tools.confirm.confirm_action", return_value=True):
        result = tools.edit_entry(entry_id=7, project="web redesign")
    assert result["ok"] is True
    edit_args = m.call_args_list[1].args[0]
    assert edit_args[edit_args.index("--project") + 1] == "Web Redesign"
    assert "--task" not in edit_args


def test_edit_entry_validation_runs_after_shortcut(configured_project_index):
    """A shortcut resolving to a bogus project gets rejected by validation."""
    tools.configure(
        shortcuts=[Shortcut(name="bogus", project="Imaginary", task="Whatever")],
        project_index=tools._context.project_index,
    )
    try:
        fake_today = _harvest_view_json([_entry(7)])
        with patch("harvest_agent.tools.harvest_cli.run", side_effect=[fake_today]) as m, \
             patch("harvest_agent.tools.confirm.confirm_action", return_value=True):
            result = tools.edit_entry(entry_id=7, project="bogus")
        assert result["ok"] is False
        assert "Imaginary" in result["stderr"]
        edit_calls = [c for c in m.call_args_list if c.args[0][0] == "edit"]
        assert edit_calls == []
    finally:
        tools.configure()
