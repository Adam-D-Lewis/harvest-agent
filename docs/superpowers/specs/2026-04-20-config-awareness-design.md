# Passive config-file awareness (reactive) — design

**Date:** 2026-04-20
**Status:** Approved (design); implementation pending
**Scope:** One small change to the system prompt + supporting wiring/tests.

## Motivation

The harvest agent already reads the user's preferences at startup — `shortcut`,
`recurring_meeting`, and `behavior` blocks from
`~/.config/harvest-agent/config.toml` are rendered into the system prompt and
used by the tools. Two gaps:

1. The agent doesn't know the **path** to the file, so when the user asks
   "where are my preferences?" or "remember that mentoring goes under
   Admin / People Management," it can't give a useful answer.
2. The base instructions say "You cannot run shell commands, read arbitrary
   files, or access the network directly," which is true of the running
   agent but misleadingly suggests it doesn't know where its config lives.

The fix is **reactive** and **passive**: the agent gains awareness of the
config file (path + schema) so it can direct the user when asked, but does
not gain a tool to edit the file, and does not proactively nag.

A structured edit tool (`add_shortcut`, etc.) is explicitly deferred to a
future change if this proves insufficient.

## Non-goals

- No edit tool.
- No proactive suggestions (user explicitly chose reactive-only).
- No hot-reload of config. Config changes take effect on the next agent
  restart — the agent tells the user this whenever it suggests an edit.
- Not addressing the separate "agent didn't check existing entries before
  logging" gap surfaced in the same conversation. That's a different design.

## Design

### 1. System prompt — new section

`src/harvest_agent/prompt.py` gains a new section, appended at the end of
the prompt (after the existing `Behavior preferences` block), titled
**"Your preferences file"**:

```
## Your preferences file

Your shortcuts, recurring meetings, and behavior notes above are loaded from:
  <absolute path to config.toml>

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
notes = """
...existing lines...
<your new line>
"""
```

### 2. Base-instructions tweak

Line 10 of `_BASE_INSTRUCTIONS`:

> "You cannot run shell commands, read arbitrary files, or access the network directly."

becomes:

> "You cannot run shell commands or access the network directly. You know where your preferences file lives (see below) but cannot edit it — the user edits it manually."

### 3. Wiring

- `build_system_prompt(cfg, today, project_index=None)` gains a new
  keyword-only argument: `config_path: Path | None = None`.
- If `config_path` is `None`, the new "Your preferences file" section is
  omitted entirely (the old test fixtures still pass unchanged; also keeps
  eval fixtures hermetic if they don't care about the path).
- `agent._build_agent` accepts and threads through `config_path`.
- `agent.run_repl` passes its already-resolved `config_path` (from
  `default_config_path()` or whatever was loaded) down to `_build_agent`.

### 4. Tests

Three new tests in `tests/test_prompt.py`:

- `test_prompt_includes_config_path_when_given`: passing a fake path produces
  a prompt containing that exact path string.
- `test_prompt_includes_schema_examples`: the rendered prompt contains
  `[[shortcut]]`, `[[recurring_meeting]]`, and `behavior.notes`.
- `test_prompt_omits_config_section_when_path_none`: confirms the section is
  absent when no path is passed (so existing callers/tests are unaffected).

No existing tests should need to change; the new argument is optional with
a None default.

## Risks and mitigations

- **Prompt length.** The new section adds ~25 lines. On a small local model
  (Qwen3.6-35B-A3B) this is negligible; we already render a 21-row date
  table and full shortcut / project tables.
- **Model misinterprets "cannot edit" and tries anyway.** The agent has no
  file-editing tool registered, so even a hallucinated edit attempt will
  fail at the tool-dispatch level. Worst case is a confusing tool-not-found
  error rather than silent corruption.
- **User edits config incorrectly after agent suggestion.** The TOML schema
  is already validated on load (`Config.model_validate` in `config.py:109`);
  a bad edit produces a clear `ConfigError` at startup rather than silent
  wrong behavior.

## Out of scope / future work

- **Option (b): structured edit tool.** Would add e.g. `add_shortcut(...)`
  that appends to the TOML file, gated by the existing confirmation-diff
  flow (`confirm.py`). Revisit if passive awareness proves insufficient.
- **Config hot-reload.** Not worth the complexity for this use case.
- **Proactive suggestions** when the agent notices repeated unmapped terms.
  User explicitly preferred reactive-only to avoid noise.

## Estimated size

~25 lines added to `prompt.py`, ~3 lines changed in `agent.py`, ~15 lines
of tests. Single self-contained change, no new dependencies.
