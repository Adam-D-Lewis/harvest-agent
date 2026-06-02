from datetime import date
from pathlib import Path

from harvest_agent.config import Config
from harvest_agent.project_index import ProjectInfo
from harvest_agent.prompt import build_system_prompt


def _config_dict():
    return {
        "user": {"name": "Jane"},
        "shortcut": [
            {"name": "acme", "project": "Web Redesign", "task": "Programming", "notes": "default"},
        ],
        "recurring_meeting": [
            {"day": "tuesday", "project": "Web Redesign", "task": "Meetings / Standups", "hours": 1.0},
        ],
        "behavior": {"flag_weekends": True, "notes": "no weekend work"},
    }


def test_prompt_includes_user_name():
    cfg = Config.model_validate(_config_dict())
    prompt = build_system_prompt(cfg, today=date(2026, 4, 7))
    assert "Jane" in prompt


def test_prompt_includes_today_date():
    cfg = Config.model_validate(_config_dict())
    prompt = build_system_prompt(cfg, today=date(2026, 4, 7))
    assert "2026-04-07" in prompt


def test_prompt_includes_weekday_name():
    # Local models hallucinate day-of-week from bare ISO dates, so the prompt
    # must spell out the weekday. Apr 7 2026 is a Tuesday.
    cfg = Config.model_validate(_config_dict())
    prompt = build_system_prompt(cfg, today=date(2026, 4, 7))
    assert "Tuesday" in prompt


def test_prompt_includes_three_week_date_table():
    """The prompt must list all 21 ISO dates from last Mon through next Sun.

    The model can't reliably do calendar math, so the prompt must spell out
    every nearby date. After we removed the 'next/last <day>' parser
    branches, this 3-week table is the model's only deterministic source for
    any date beyond ±1 day from today.
    """
    cfg = Config.model_validate(_config_dict())
    # Apr 7 2026 is a Tuesday, so the 3-week range (Mon of last week →
    # Sun of next week) runs Mar 30 through Apr 19.
    prompt = build_system_prompt(cfg, today=date(2026, 4, 7))
    expected_dates = [
        # Last week (Mon Mar 30 — Sun Apr 5)
        "2026-03-30", "2026-03-31", "2026-04-01", "2026-04-02",
        "2026-04-03", "2026-04-04", "2026-04-05",
        # This week (Mon Apr 6 — Sun Apr 12)
        "2026-04-06", "2026-04-07", "2026-04-08", "2026-04-09",
        "2026-04-10", "2026-04-11", "2026-04-12",
        # Next week (Mon Apr 13 — Sun Apr 19)
        "2026-04-13", "2026-04-14", "2026-04-15", "2026-04-16",
        "2026-04-17", "2026-04-18", "2026-04-19",
    ]
    for d in expected_dates:
        assert d in prompt, f"missing {d} in three-week date table"
    # The heading must clearly say the table covers three weeks.
    assert "Last week, this week, and next" in prompt
    # Today must still be marked.
    assert "<- today" in prompt


def test_prompt_three_week_table_today_marker_in_middle_week():
    """The 'today' marker must land on today, not on the same weekday in
    the adjacent weeks. Today = Wed 2026-04-08, so the marker must be on
    that line and NOT on 2026-04-01 (Wed of last week) or 2026-04-15
    (Wed of next week)."""
    cfg = Config.model_validate(_config_dict())
    prompt = build_system_prompt(cfg, today=date(2026, 4, 8))

    # Look only at indented table rows (the "Today's date:" line is at column 0).
    table_rows = [ln for ln in prompt.splitlines() if ln.startswith("  Wed ")]
    assert len(table_rows) == 3, f"expected 3 Wed table rows, got {table_rows}"
    marked = [ln for ln in table_rows if "<- today" in ln]
    assert len(marked) == 1, f"expected exactly one marked Wed row, got {marked}"
    assert "2026-04-08" in marked[0]


def test_prompt_includes_shortcut_table():
    cfg = Config.model_validate(_config_dict())
    prompt = build_system_prompt(cfg, today=date(2026, 4, 7))
    assert "acme" in prompt
    assert "Web Redesign" in prompt
    assert "Programming" in prompt


def test_prompt_includes_recurring_meetings():
    cfg = Config.model_validate(_config_dict())
    prompt = build_system_prompt(cfg, today=date(2026, 4, 7))
    assert "tuesday" in prompt.lower()
    assert "Meetings / Standups" in prompt


def test_prompt_includes_behavior_notes_verbatim():
    cfg = Config.model_validate(_config_dict())
    prompt = build_system_prompt(cfg, today=date(2026, 4, 7))
    assert "no weekend work" in prompt


def test_prompt_no_longer_documents_next_or_last_dayname_forms():
    """The prompt must not advertise 'next <day>' or 'last <day>' as valid
    date forms — they were ambiguous and have been removed from the parser."""
    cfg = Config.model_validate(_config_dict())
    prompt = build_system_prompt(cfg, today=date(2026, 4, 7))
    # The base instructions used to list "next Monday" and "last Friday" as
    # examples; both must be gone.
    assert "next Monday" not in prompt
    assert "last Friday" not in prompt
    # The replacement guidance must explicitly tell the model to use the table.
    assert "Last week, this week, and next" in prompt  # heading reference


def test_prompt_includes_safety_rules():
    cfg = Config.model_validate(_config_dict())
    prompt = build_system_prompt(cfg, today=date(2026, 4, 7))
    # The agent must know about quarter-hour rounding and confirmation behaviour.
    assert "0.25" in prompt or "quarter" in prompt.lower()
    assert "edit" in prompt.lower() and "delete" in prompt.lower()


def test_prompt_handles_empty_config():
    cfg = Config.model_validate({})
    prompt = build_system_prompt(cfg, today=date(2026, 4, 7))
    assert prompt  # doesn't crash
    assert "2026-04-07" in prompt


def _sample_index():
    return {
        "web redesign": ProjectInfo(
            canonical_name="Web Redesign",
            tasks={"programming": "Programming", "meetings / standups": "Meetings / Standups"},
            client="Acme Corp",
        ),
        "admin": ProjectInfo(
            canonical_name="Admin",
            tasks={"misc": "Misc"},
            client="OpenTeams, Inc.",
        ),
    }


def test_prompt_includes_projects_and_tasks_section_when_index_provided():
    cfg = Config.model_validate(_config_dict())
    prompt = build_system_prompt(cfg, today=date(2026, 4, 7), project_index=_sample_index())
    assert "## Projects and tasks" in prompt
    assert "Web Redesign" in prompt
    assert "Programming" in prompt
    assert "Meetings / Standups" in prompt
    assert "Admin" in prompt
    assert "Misc" in prompt
    # Clients must be surfaced so the model can resolve work named by client.
    assert "Acme Corp" in prompt
    assert "OpenTeams, Inc." in prompt


def test_prompt_projects_section_shows_client_on_same_line_as_project():
    """Each project line must name its client, so the model can map a request
    phrased by client name (e.g. "log under Acme Corp") to the right project."""
    cfg = Config.model_validate(_config_dict())
    prompt = build_system_prompt(cfg, today=date(2026, 4, 7), project_index=_sample_index())
    project_lines = [ln for ln in prompt.splitlines() if ln.startswith("- **Web Redesign**")]
    assert len(project_lines) == 1
    assert "Acme Corp" in project_lines[0]


def test_prompt_projects_section_omits_client_annotation_when_blank():
    """A project with no client (e.g. fetch lacked the field) renders without
    a dangling '(client: )' marker."""
    cfg = Config.model_validate(_config_dict())
    index = {"web redesign": ProjectInfo(canonical_name="Web Redesign", tasks={"programming": "Programming"})}
    prompt = build_system_prompt(cfg, today=date(2026, 4, 7), project_index=index)
    assert "client:" not in prompt


def test_prompt_omits_projects_section_when_index_empty():
    cfg = Config.model_validate(_config_dict())
    prompt = build_system_prompt(cfg, today=date(2026, 4, 7), project_index={})
    assert "## Projects and tasks" not in prompt


def test_prompt_omits_projects_section_when_index_not_passed():
    cfg = Config.model_validate(_config_dict())
    prompt = build_system_prompt(cfg, today=date(2026, 4, 7))
    assert "## Projects and tasks" not in prompt


def test_prompt_includes_config_path_when_given():
    cfg = Config.model_validate(_config_dict())
    fake_path = Path("/tmp/fake-harvest-agent/config.toml")
    prompt = build_system_prompt(cfg, today=date(2026, 4, 7), config_path=fake_path)
    assert str(fake_path) in prompt
    assert "## Your preferences file" in prompt


def test_prompt_includes_schema_examples_when_config_path_given():
    cfg = Config.model_validate(_config_dict())
    prompt = build_system_prompt(
        cfg, today=date(2026, 4, 7), config_path=Path("/tmp/cfg.toml")
    )
    # The three schema shapes the agent should paste back to the user.
    assert "[[shortcut]]" in prompt
    assert "[[recurring_meeting]]" in prompt
    assert "behavior.notes" in prompt or "[behavior]" in prompt


def test_prompt_omits_preferences_file_section_when_config_path_none():
    """Default behaviour: callers that don't pass a config_path get no new
    section. Keeps existing tests and eval fixtures unaffected."""
    cfg = Config.model_validate(_config_dict())
    prompt = build_system_prompt(cfg, today=date(2026, 4, 7))
    assert "## Your preferences file" not in prompt
