"""Build the agent's system prompt from a Config."""

from datetime import date, timedelta
from pathlib import Path

from harvest_agent.config import Config
from harvest_agent.project_index import ProjectIndex

_BASE_INSTRUCTIONS = """\
You are a Harvest time-tracking assistant. Your only capability is calling the
harvest tools provided. You cannot run shell commands or access the network
directly. You know where your preferences file lives (see "Your preferences
file" below, when present) but cannot edit it — the user edits it manually.

The tools do several things automatically so you don't have to:

- **Shortcut resolution**: If the user mentions a shortcut name from the table
  below (e.g. "acme", "mobile meeting"), pass that name AS-IS as the `project`
  argument to log_time or edit_entry. Pass an empty string "" for `task`.
  The tool will resolve both project and task from the shortcut. Do NOT look
  up the table yourself and copy the strings — just pass the shortcut name
  verbatim.
- **Date parsing**: The `date` argument to log_time accepts "today",
  "yesterday", "tomorrow", "this Friday", and ISO YYYY-MM-DD. For any other
  date, look up the ISO date in the "Last week, this week, and next" table
  in your context and pass that. Do NOT say "next <day>" or "last <day>" —
  these are ambiguous in English (e.g. "last Tuesday" can mean yesterday OR
  Tuesday of the previous calendar week) and the tool will reject them.
  Do NOT compute calendar dates yourself; use the table.
- **Hour rounding**: Pass raw hours values. The tool rounds to the nearest
  0.25 automatically. Do NOT pre-round.

If a tool's return value contains `tool_notes`, mention them to the user so
they know what was auto-resolved.

Other rules:
- **Never substitute a project or task the user didn't ask for.** If the user
  names a project or task that isn't in the "Projects and tasks" section, do
  NOT pick a different one that sounds similar or seems related. Tell the user
  the project (or task) doesn't exist, list the valid ones, and ask which they
  meant. The Projects and tasks list is the complete set — there is no "close
  enough."
- When you call edit_entry or delete_entry, the user will be shown a confirmation
  prompt with a before/after diff. If they decline, the tool returns
  "user cancelled" — tell the user clearly and stop, don't retry.
- Always pass `notes` (even "") and `date` to log_time, never omit them.
  If the user didn't mention a date, pass "today".
- When showing entries, prefer parsing the JSON from view tools and presenting
  a clean summary, not the raw blob.
- If a tool returns an error about authentication, tell the user to check their
  HARVEST_TOKEN — never echo any value.
"""


def _format_shortcuts(cfg: Config) -> str:
    if not cfg.shortcut:
        return ""
    lines = ["## Shortcut mappings\n", "| Shorthand | Project | Task | Notes |", "|---|---|---|---|"]
    for s in cfg.shortcut:
        lines.append(f"| {s.name} | {s.project} | {s.task} | {s.notes or ''} |")
    return "\n".join(lines)


def _format_recurring(cfg: Config) -> str:
    if not cfg.recurring_meeting:
        return ""
    lines = ["## Recurring meetings\n"]
    for m in cfg.recurring_meeting:
        lines.append(f"- **{m.day}**: {m.project} / {m.task} — {m.hours}h")
    return "\n".join(lines)


def _format_projects_and_tasks(project_index: ProjectIndex) -> str:
    if not project_index:
        return ""
    lines = [
        "## Projects and tasks\n",
        "Only these projects and tasks exist. Use the exact spelling shown — "
        "the tools are case-insensitive but won't accept invented names. Each "
        "project belongs to a client (shown in parentheses). If the user refers "
        "to work by its client name, map it to the project(s) under that client; "
        "if a client owns more than one project, ask which they mean rather than "
        "guessing.\n",
    ]
    # Sort by canonical name for stable output
    for info in sorted(project_index.values(), key=lambda i: i.canonical_name):
        task_list = ", ".join(sorted(info.tasks.values())) if info.tasks else "(no tasks)"
        client_suffix = f" (client: {info.client})" if info.client else ""
        lines.append(f"- **{info.canonical_name}**{client_suffix}: {task_list}")
    return "\n".join(lines)


def _format_behavior(cfg: Config) -> str:
    parts = ["## Behavior preferences\n"]
    if cfg.behavior.flag_weekends:
        parts.append("- Flag entries on Saturday or Sunday as unusual.")
    if cfg.behavior.auto_split_meetings:
        parts.append("- When logging a day, split out recurring meeting hours into separate entries automatically.")
    if cfg.behavior.notes:
        parts.append("\n" + cfg.behavior.notes.strip())
    if len(parts) == 1:
        return ""
    return "\n".join(parts)


def _format_preferences_file(config_path: Path | None) -> str:
    """Render a section telling the model where config.toml lives and how to
    suggest edits. Returns '' if no path was supplied so the section is
    simply absent for callers that don't care (tests, evals).

    The agent has no file-editing tool — this section exists so the model
    can answer 'where are my preferences?' with the real path plus a
    ready-to-paste TOML snippet, and explicitly tell the user that changes
    take effect only on the next agent restart.
    """
    if config_path is None:
        return ""
    return f"""## Your preferences file

Your shortcuts, recurring meetings, and behavior notes above are loaded from:
  {config_path}

You cannot edit this file yourself. When the user asks where preferences
live, says "remember this", asks to add a shortcut, or otherwise wants to
change their preferences, respond with:

1. The file path above.
2. A ready-to-paste TOML snippet in a fenced code block.
3. A one-line note that changes take effect on the next agent restart.

Snippet schemas (copy the shape, fill in values):

[[shortcut]]
name = "<short name user will type>"
project = "<exact project name from Projects and tasks>"
task = "<exact task name>"
notes = "<optional default notes>"

[[recurring_meeting]]
day = "monday"   # monday..sunday
project = "<project>"
task = "<task>"
hours = 1.0

# For free-form guidance, append a line inside the existing behavior.notes block:
[behavior]
notes = \"\"\"
...existing lines...
<your new line>
\"\"\"
"""


def _format_three_weeks(today: date) -> str:
    """Render last week, this week, and next week (Mon-Sun each) as a
    weekday→date table.

    After the parser stopped accepting 'next <day>' / 'last <day>' (both
    ambiguous in conversational English), this 3-week table is the model's
    only deterministic source for any date beyond ±1 day from today. Spelling
    out every row eliminates the calendar arithmetic that small models
    routinely get wrong.
    """
    monday_this_week = today - timedelta(days=today.weekday())
    monday_last_week = monday_this_week - timedelta(days=7)
    lines = ["Last week, this week, and next:"]
    for i in range(21):
        d = monday_last_week + timedelta(days=i)
        marker = "  <- today" if d == today else ""
        lines.append(f"  {d.strftime('%a')} {d.isoformat()}{marker}")
    return "\n".join(lines)


def build_system_prompt(
    cfg: Config,
    today: date,
    project_index: ProjectIndex | None = None,
    config_path: Path | None = None,
) -> str:
    """Build the full system prompt for the agent."""
    # Spell the date out two ways for the model: weekday-named today, then
    # a 21-row table covering Mon-of-last-week through Sun-of-next-week.
    # Small/local models hallucinate day-of-week from a bare ISO date and
    # cannot reliably do calendar arithmetic; the table eliminates both
    # failure modes for any date in the ±1 week range. Anything further out
    # has to be passed as ISO directly.
    sections = [
        _BASE_INSTRUCTIONS,
        f"\nToday's date: {today.strftime('%A, %Y-%m-%d')}",
        _format_three_weeks(today),
    ]
    if cfg.user.name:
        sections.append(f"User: {cfg.user.name}")

    shortcuts_block = _format_shortcuts(cfg)
    if shortcuts_block:
        sections.append("\n" + shortcuts_block)

    projects_block = _format_projects_and_tasks(project_index or {})
    if projects_block:
        sections.append("\n" + projects_block)

    for builder in (_format_recurring, _format_behavior):
        block = builder(cfg)
        if block:
            sections.append("\n" + block)

    prefs_block = _format_preferences_file(config_path)
    if prefs_block:
        sections.append("\n" + prefs_block)

    return "\n".join(sections)
