import pytest
from harvest_agent.config import Config, Shortcut, RecurringMeeting


def test_config_from_full_dict():
    data = {
        "user": {"name": "Jane Smith"},
        "shortcut": [
            {"name": "acme", "project": "Web Redesign", "task": "Programming"},
            {"name": "acme meeting", "project": "Web Redesign", "task": "Meetings / Standups", "notes": "Tue/Thu"},
        ],
        "recurring_meeting": [
            {"day": "tuesday", "project": "Web Redesign", "task": "Meetings / Standups", "hours": 1.0},
        ],
        "behavior": {"flag_weekends": True, "auto_split_meetings": True, "notes": "no weekends"},
    }
    cfg = Config.model_validate(data)
    assert cfg.user.name == "Jane Smith"
    assert len(cfg.shortcut) == 2
    assert cfg.shortcut[0].name == "acme"
    assert cfg.recurring_meeting[0].day == "tuesday"
    assert cfg.behavior.flag_weekends is True


def test_config_rejects_bad_day():
    data = {"recurring_meeting": [{"day": "tooseday", "project": "X", "task": "Y", "hours": 1.0}]}
    with pytest.raises(Exception):
        Config.model_validate(data)


def test_config_rejects_missing_shortcut_field():
    data = {"shortcut": [{"name": "x", "project": "p"}]}  # missing task
    with pytest.raises(Exception):
        Config.model_validate(data)


def test_config_empty_is_valid():
    cfg = Config.model_validate({})
    assert cfg.shortcut == []
    assert cfg.recurring_meeting == []
    assert cfg.user.name is None


def test_behavior_unusual_project_window_days_default():
    cfg = Config.model_validate({})
    assert cfg.behavior.unusual_project_window_days == 30


def test_behavior_unusual_project_window_days_custom():
    cfg = Config.model_validate({"behavior": {"unusual_project_window_days": 60}})
    assert cfg.behavior.unusual_project_window_days == 60


from pathlib import Path
from harvest_agent.config import load_config, ConfigError, default_config_path


def test_load_config_from_toml(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[user]\nname = "Jane"\n'
        '[[shortcut]]\nname = "g"\nproject = "Web Redesign"\ntask = "Programming"\n'
    )
    cfg = load_config(p)
    assert cfg.user.name == "Jane"
    assert cfg.shortcut[0].name == "g"


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml")


def test_load_config_invalid_toml_raises(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("this is = not valid = toml [[[")
    with pytest.raises(ConfigError, match="parse"):
        load_config(p)


def test_load_config_invalid_schema_raises(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[[recurring_meeting]]\nday = "noday"\nproject = "X"\ntask = "Y"\nhours = 1.0\n'
    )
    with pytest.raises(ConfigError, match="schema"):
        load_config(p)


def test_default_config_path_uses_xdg():
    p = default_config_path()
    assert p.name == "config.toml"
    assert "harvest-agent" in str(p)


from harvest_agent.config import scaffold_config


def test_scaffold_writes_a_valid_minimal_file(tmp_path):
    p = tmp_path / "config.toml"
    scaffold_config(p)
    assert p.exists()
    cfg = load_config(p)
    assert cfg.shortcut == []
    assert cfg.user.name is None


def test_scaffold_creates_parent_dirs(tmp_path):
    p = tmp_path / "subdir" / "config.toml"
    scaffold_config(p)
    assert p.exists()


def test_scaffold_does_not_overwrite_existing(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("existing = true")
    with pytest.raises(ConfigError, match="exists"):
        scaffold_config(p)
