"""User configuration schema for harvest-agent."""

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

Day = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class User(BaseModel):
    name: str | None = None


class Shortcut(BaseModel):
    name: str
    project: str
    task: str
    notes: str | None = None


class RecurringMeeting(BaseModel):
    day: Day
    project: str
    task: str
    hours: float


class Behavior(BaseModel):
    flag_weekends: bool = False
    auto_split_meetings: bool = False
    notes: str | None = None


class Config(BaseModel):
    user: User = Field(default_factory=User)
    shortcut: list[Shortcut] = Field(default_factory=list)
    recurring_meeting: list[RecurringMeeting] = Field(default_factory=list)
    behavior: Behavior = Field(default_factory=Behavior)


class ConfigError(Exception):
    """Raised when the user's config file cannot be loaded or validated."""


def default_config_path() -> Path:
    """Return the default config path: $XDG_CONFIG_HOME/harvest-agent/config.toml."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "harvest-agent" / "config.toml"


_SCAFFOLD_TEMPLATE = '''\
# Harvest Agent configuration
# See README.md for the full schema.

[user]
# name = "Your Name"

# Shortcut mappings — quick references the agent will recognize.
# Add one [[shortcut]] block per shortcut you want.
#
# [[shortcut]]
# name = "acme"
# project = "Web Redesign"
# task = "Programming"
# notes = "Default Acme Corp work"

# Recurring meetings — the agent will use these when auto-splitting a day's hours.
#
# [[recurring_meeting]]
# day = "tuesday"
# project = "Web Redesign"
# task = "Meetings / Standups"
# hours = 1.0

[behavior]
flag_weekends = true
auto_split_meetings = true
notes = """
Free-form behavior notes for the agent. The LLM reads this verbatim.
Examples:
- Always round to the nearest 0.25 hours.
- I don't typically work on weekends; flag if you see weekend entries.
"""
'''


def scaffold_config(path: Path) -> None:
    """Write a minimal starter config to `path`. Refuses to overwrite."""
    if path.exists():
        raise ConfigError(f"Config file already exists at {path}, refusing to overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_SCAFFOLD_TEMPLATE)


def load_config(path: Path) -> Config:
    """Load and validate a config TOML file. Raises ConfigError on any failure."""
    if not path.exists():
        raise ConfigError(f"Config file not found at {path}")
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Could not parse {path}: {e}") from e
    try:
        return Config.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(f"Config file {path} failed schema validation: {e}") from e
