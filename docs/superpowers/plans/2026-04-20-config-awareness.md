# Passive Config Awareness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach the harvest agent where its `config.toml` lives and what its schema looks like, so it can respond to "remember this" / "where are my preferences?" with a file path and a ready-to-paste TOML snippet — without gaining any file-editing capability.

**Architecture:** A new optional `config_path: Path | None` parameter flows from `run_repl` → `_build_agent` → `build_system_prompt`. When provided, `build_system_prompt` appends a "Your preferences file" section after the existing behavior block. The base-instructions line that says "cannot read arbitrary files" is softened so the model doesn't refuse to discuss config. No tools added, no existing tools changed, no new dependencies.

**Tech Stack:** Python 3.11+, PydanticAI, pytest. Existing `src/harvest_agent/prompt.py`, `src/harvest_agent/agent.py`, and their test files.

**Spec:** `docs/superpowers/specs/2026-04-20-config-awareness-design.md`

---

## File Structure

**Modified:**
- `src/harvest_agent/prompt.py` — new `_format_preferences_file(config_path)` helper; new kwarg on `build_system_prompt`; one-line tweak to `_BASE_INSTRUCTIONS`
- `src/harvest_agent/agent.py` — `_build_agent` accepts `config_path`; `run_repl` passes the resolved `config_path` through
- `tests/test_prompt.py` — three new tests (include-path, include-schema, omit-when-none)
- `tests/test_agent.py` — one new test (config_path threads from `_build_agent` into the generated prompt)

**Not modified:** tools, harvest_cli, confirm, show_config, project_index.

---

## Task 1: Add "Your preferences file" section to the system prompt

**Files:**
- Modify: `src/harvest_agent/prompt.py`
- Test: `tests/test_prompt.py`

- [ ] **Step 1: Write the three failing tests**

Add to the end of `tests/test_prompt.py`:

```python
from pathlib import Path


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
```

- [ ] **Step 2: Run the new tests and confirm they fail**

Run: `pixi run pytest tests/test_prompt.py -v -k "config_path or preferences_file or schema_examples"`

Expected: all three FAIL with `TypeError: build_system_prompt() got an unexpected keyword argument 'config_path'` (for the first two) and the third also fails because of the same TypeError — or passes vacuously; if it passes at this stage that's fine, it will still pass at the end.

- [ ] **Step 3: Implement the new helper in `prompt.py`**

Add this import at the top of `src/harvest_agent/prompt.py` (alongside the existing `from datetime import date, timedelta`):

```python
from pathlib import Path
```

Add this new helper function immediately after `_format_behavior` (after line 96):

```python
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
```

- [ ] **Step 4: Add the `config_path` parameter to `build_system_prompt` and append the new section**

Replace the existing `build_system_prompt` function (lines 119–152) with:

```python
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
```

- [ ] **Step 5: Soften the base-instructions line about reading files**

Replace the first sentence in `_BASE_INSTRUCTIONS` (currently lines 9–11):

```python
_BASE_INSTRUCTIONS = """\
You are a Harvest time-tracking assistant. Your only capability is calling the
harvest tools provided. You cannot run shell commands, read arbitrary files, or
access the network directly.
```

with:

```python
_BASE_INSTRUCTIONS = """\
You are a Harvest time-tracking assistant. Your only capability is calling the
harvest tools provided. You cannot run shell commands or access the network
directly. You know where your preferences file lives (see "Your preferences
file" below, when present) but cannot edit it — the user edits it manually.
```

- [ ] **Step 6: Run the new tests and confirm they pass**

Run: `pixi run pytest tests/test_prompt.py -v -k "config_path or preferences_file or schema_examples"`

Expected: all three PASS.

- [ ] **Step 7: Run the full test suite and confirm no regressions**

Run: `pixi run pytest -q`

Expected: all tests pass. Pay particular attention to the existing `test_prompt_*` tests — none of them pass `config_path`, so they must still pass unchanged.

- [ ] **Step 8: Commit**

```bash
git add src/harvest_agent/prompt.py tests/test_prompt.py
git commit -m "prompt: add optional preferences-file section

When build_system_prompt is passed config_path, it appends a section
telling the agent where config.toml lives and the TOML schema for
shortcuts, recurring meetings, and behavior notes. The agent uses this
to answer 'where are my preferences?' / 'remember this' reactively,
without any file-editing capability.

Also softens the base-instructions line that said 'cannot read arbitrary
files' so the model doesn't refuse to discuss config.

Callers that don't pass config_path get no new section — keeps existing
tests and eval fixtures unaffected."
```

---

## Task 2: Thread `config_path` through `_build_agent` and `run_repl`

**Files:**
- Modify: `src/harvest_agent/agent.py`
- Test: `tests/test_agent.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_agent.py` (alongside the other `_build_agent` tests):

```python
from pathlib import Path


def test_agent_build_threads_config_path_into_system_prompt():
    """_build_agent should pass config_path through to build_system_prompt
    so the rendered system prompt contains the preferences-file section."""
    fake_path = Path("/tmp/fake-harvest-agent/config.toml")
    with patch("harvest_agent.agent.build_project_index", return_value={}):
        agent = _build_agent(
            Config(),
            model=TestModel(call_tools=[]),
            today=date(2026, 4, 8),
            config_path=fake_path,
        )
    # PydanticAI Agent exposes its system prompt(s) via ._system_prompts.
    # The path string should appear in the rendered prompt.
    rendered = "\n".join(agent._system_prompts)
    assert str(fake_path) in rendered
    assert "## Your preferences file" in rendered
    tools.configure()  # reset
```

Note: if `agent._system_prompts` is not the correct attribute in the installed PydanticAI version, fall back to checking via `agent._instructions` or inspect `agent` in a quick `python -c` session to find where the rendered system prompt is stored. The test body should assert on whichever attribute the installed version exposes.

- [ ] **Step 2: Run the new test and confirm it fails**

Run: `pixi run pytest tests/test_agent.py::test_agent_build_threads_config_path_into_system_prompt -v`

Expected: FAIL with `TypeError: _build_agent() got an unexpected keyword argument 'config_path'`.

- [ ] **Step 3: Update `_build_agent` to accept and thread `config_path`**

In `src/harvest_agent/agent.py`, replace the existing `_build_agent` (lines 102–135) with:

```python
def _build_agent(
    cfg: Config,
    model=None,
    today: date | None = None,
    config_path: Path | None = None,
) -> Agent:
    if model is None:
        model = _resolve_model()
    if today is None:
        today = date.today()
    # Fetch project + task index for validation and prompt rendering. On
    # failure (auth error, CLI missing) the builder returns {} and prints a
    # warning; we still construct the agent so view tools keep working.
    project_index = build_project_index()
    # Install config-derived state into the tools module so individual tool
    # functions can resolve shortcuts, parse relative dates, and validate
    # project/task names against the same data the system prompt saw.
    tools.configure(shortcuts=cfg.shortcut, today=today, project_index=project_index)
    agent = Agent(
        model=model,
        system_prompt=build_system_prompt(
            cfg,
            today=today,
            project_index=project_index,
            config_path=config_path,
        ),
    )

    # Read-only
    agent.tool_plain(tools.view_today)
    agent.tool_plain(tools.view_week)
    agent.tool_plain(tools.view_range)
    agent.tool_plain(tools.list_projects)
    agent.tool_plain(tools.list_tasks)
    agent.tool_plain(tools.status)
    # Additive
    agent.tool_plain(tools.log_time)
    agent.tool_plain(tools.start_timer)
    agent.tool_plain(tools.stop_timer)
    # Destructive (gated by confirm.confirm_action inside the tool)
    agent.tool_plain(tools.edit_entry)
    agent.tool_plain(tools.delete_entry)

    return agent
```

Also add at the top of `src/harvest_agent/agent.py` (alongside the existing `from datetime import date`):

```python
from pathlib import Path
```

- [ ] **Step 4: Pass `config_path` from `run_repl` into `_build_agent`**

In `src/harvest_agent/agent.py`, replace the line in `run_repl` that currently reads (around line 168):

```python
    agent = _build_agent(cfg)
```

with:

```python
    agent = _build_agent(cfg, config_path=config_path)
```

The `config_path` variable is already in scope from line 140.

- [ ] **Step 5: Run the new test and confirm it passes**

Run: `pixi run pytest tests/test_agent.py::test_agent_build_threads_config_path_into_system_prompt -v`

Expected: PASS. If it fails because `agent._system_prompts` doesn't exist in this PydanticAI version, inspect the agent object (`python -c "from pydantic_ai import Agent; a = Agent(model='test', system_prompt='x'); print(dir(a))"`) to find the correct attribute, then update the test's assertion target. Do NOT change the implementation — only the test's introspection.

- [ ] **Step 6: Run the full test suite and confirm no regressions**

Run: `pixi run pytest -q`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/harvest_agent/agent.py tests/test_agent.py
git commit -m "agent: thread config_path into system prompt

_build_agent now accepts config_path and passes it through to
build_system_prompt, and run_repl supplies the already-resolved path.
The preferences-file section is now live in the actual REPL."
```

---

## Task 3: Manual verification

**Files:** none — this is a smoke test against a live agent.

- [ ] **Step 1: Start the agent**

Run: `harvest-agent` (from any directory — the alias points at this repo after the earlier alias fix).

Expected banner: `Harvest Agent ready (model=Qwen3.6-35B-A3B @ http://localhost:8080/v1, config=/home/balast/.config/harvest-agent/config.toml)`.

- [ ] **Step 2: Ask about the preferences file**

At the `You>` prompt, type: `where are my preferences saved?`

Expected: the agent names the exact path (`/home/balast/.config/harvest-agent/config.toml`) and mentions it can't edit the file itself. If it apologizes and says it can't read any files, the `_BASE_INSTRUCTIONS` softening didn't take — re-check Task 1 Step 5.

- [ ] **Step 3: Ask for a shortcut addition**

At the `You>` prompt, type: `remember that mentoring should go under Admin / People Management`

Expected: the agent replies with
1. The file path,
2. A TOML snippet showing a `[[shortcut]]` block with `name = "mentoring"`, `project = "Admin"`, `task = "People Management"`,
3. A note that the change takes effect after an agent restart.

If the agent instead tries to call a (nonexistent) file-edit tool or invents an `edit_config` tool, that's a model hallucination — note it but do not add a tool. The prompt's explicit "you cannot edit this file yourself" line is our mitigation.

- [ ] **Step 4: Record the manual-verification outcome**

Append a short entry to `proof.md` describing: command invoked, questions asked, actual agent responses (copy the relevant lines). Commit:

```bash
git add proof.md
git commit -m "proof: record manual verification of preferences-file awareness"
```

---

## Self-review (done before presenting plan)

**Spec coverage:**
- System prompt "Your preferences file" section → Task 1 Steps 3–4
- `_BASE_INSTRUCTIONS` softening → Task 1 Step 5
- `config_path` threaded through `_build_agent` and `run_repl` → Task 2 Steps 3–4
- Three new test functions in `tests/test_prompt.py` → Task 1 Step 1
- New test in `tests/test_agent.py` → Task 2 Step 1
- Section omitted when `config_path=None` → covered by `_format_preferences_file` returning `""` and by `test_prompt_omits_preferences_file_section_when_config_path_none`

**Placeholder scan:** No TBD / TODO / "implement later" entries. Only placeholders in content are the intentional `<short name user will type>` etc. strings in the rendered prompt, which are literal output.

**Type consistency:** `config_path: Path | None = None` used consistently in `_format_preferences_file`, `build_system_prompt`, and `_build_agent`. `from pathlib import Path` added to both `prompt.py` and `agent.py`.

**Scope:** single small feature, single spec, one plan.
