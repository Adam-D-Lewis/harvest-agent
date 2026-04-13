# Harvest Agent — Proof of Work

End-to-end demonstration of the harvest-agent working against a real Harvest account, driven by a local model served by `llama.cpp`.

## Model

| | |
|---|---|
| **Provider** | llama.cpp (systemd unit: `llama-server.service`) |
| **Model** | Qwen/Qwen3-Coder-Next-GGUF:Q4_K_M |
| **Endpoint** | `http://localhost:8080/v1` (OpenAI-compatible) |
| **API key** | none (local server) |

Started with `llama-start` (alias for `systemctl --user start llama-server`). Agent pointed at it with:

```bash
export HARVEST_AGENT_BASE_URL=http://localhost:8080/v1
export HARVEST_AGENT_MODEL=Qwen3-Coder-Next
```

This triggers the `_resolve_model()` branch in `src/harvest_agent/agent.py` that builds an `OpenAIChatModel` with a custom `OpenAIProvider(base_url=...)` instead of resolving `HARVEST_AGENT_MODEL` as a PydanticAI provider string.

## Transcript

Captured from a scripted driver that runs each scenario sequentially, piping `y` or `n` to `sys.stdin` when the confirmation helper prompts. The agent's REPL loop is not exercised directly, but every tool, the confirm gate, and the system prompt flow ARE exercised end to end.

### Startup

```
======================================================================
 STARTUP: model=Qwen3-Coder-Next @ http://localhost:8080/v1
======================================================================
```

### Scenario 1 — view today (empty state)

```
USER: What did I log today?

AGENT: You haven't logged any time entries for today (2026-04-07).
```

Internals: agent called `view_today` → `harvest view today --json` returned `null` → `_parse_entries` normalised to `[]` → LLM summarised.

### Scenario 2 — week summary

```
USER: How many hours have I billed this week so far?

AGENT: You've billed **7.8 hours** this week so far, which is **22%**
of your weekly target (36h).
```

Tool call: `status` → `harvest status` returns the `25.5h/36h (71%)`-style string.

### Scenario 3 — log a tiny test entry

```
USER: Log 0.25 hours to the "acme" shortcut with the note
      "harvest-agent smoke test" for today.

AGENT: ✅ Logged **0.25 hours** to **Web Redesign / Programming** for
today with the note *"harvest-agent smoke test"*.
```

**The shortcut mapping worked.** The agent never saw Harvest project IDs — it resolved `"acme"` → `Web Redesign` → `Programming` from the shortcut table in the system prompt, then called:

```python
log_time(project="Web Redesign", task="Programming", hours=0.25,
         notes="harvest-agent smoke test", date="2026-04-07")
```

### Scenario 4 — read back to find the entry ID

```
USER: Show me today's entries again. List them with their IDs so I
      can reference them.

AGENT: Here's today's entry:

| ID          | Project       | Task        | Hours | Notes                  |
|-------------|---------------|-------------|-------|------------------------|
| 1234567890  | Web Redesign | Programming | 0.25  | harvest-agent smoke test|
```

Direct CLI verification:

```json
[
  {
    "id": 1234567890,
    "spent_date": "2026-04-07",
    "hours": 0.25,
    "notes": "harvest-agent smoke test",
    "project": {"name": "Web Redesign", ...},
    "task": {"name": "Programming", ...},
    "is_locked": false,
    ...
  }
]
```

### Scenario 5 — edit with confirmation (the money shot)

```
USER: Edit entry 1234567890 to be 0.5 hours instead.

=== Edit entry 1234567890 ===
    date: 2026-04-07
    hours: 0.25  ->  0.5
    id: 1234567890
    locked: False
    notes: harvest-agent smoke test
    project: Web Redesign
    task: Programming

Type 'y' to confirm, anything else to cancel: [y]

AGENT: ✅ Entry **1234567890** updated: **0.25 → 0.5 hours**.
```

**This is the safety gate in action.** Things to notice:

- The diff is printed **by Python**, not by the LLM. `confirm.confirm_action(...)` is called inside `tools.edit_entry` before any CLI invocation.
- Only `hours` changed (`0.25 -> 0.5`). Unchanged fields (`project`, `task`, `notes`, `date`) show once.
- The nested `project: {id, name, code}` from the harvest JSON is flattened to just `"Web Redesign"` by `_summarize_entry` — so the diff is human-readable, not raw JSON.
- The prompt blocks until stdin returns. The LLM has no way to "type y" on behalf of the user.

### Scenario 6 — delete but decline the confirmation

```
USER: Actually, delete entry 1234567890.

=== Delete entry 1234567890 ===
  This entry will be DELETED:
    id: 1234567890
    date: 2026-04-07
    hours: 0.5
    notes: harvest-agent smoke test
    project: Web Redesign
    task: Programming
    locked: False

Type 'y' to confirm, anything else to cancel: [n]

AGENT: The deletion was cancelled. Entry **1234567890** remains
unchanged at **0.5 hours**.

[VERIFY] Entry 1234567890 still present after 'n' response: True
```

After typing `n`, `harvest delete` is **never called**. The tool returns `{"ok": false, "stderr": "user cancelled delete"}`. The LLM gets that back as a normal tool result and relays the cancellation to the user. A direct `harvest view today --json` confirms the entry is still present.

### Scenario 7 — delete for real

```
USER: OK, go ahead and delete entry 1234567890 now.

=== Delete entry 1234567890 ===
  This entry will be DELETED:
    id: 1234567890
    date: 2026-04-07
    hours: 0.5
    notes: harvest-agent smoke test
    project: Web Redesign
    task: Programming
    locked: False

Type 'y' to confirm, anything else to cancel: [y]

AGENT: ✅ Entry **1234567890** deleted.

[VERIFY] Entry 1234567890 removed after 'y' response: True
```

Direct `harvest view today --json` after the delete returns `null` — the test entry is gone. State is restored.

## What this proves

| Claim | Evidence |
|---|---|
| Agent wires PydanticAI → harvest CLI end to end | Scenario 1 (tool call → CLI → result → LLM summary) |
| Shortcut mappings from `config.toml` work | Scenario 3 ("acme" → Web Redesign / Programming) |
| Additive ops are unrestricted | Scenario 3 (no confirmation prompt for `log_time`) |
| `edit_entry` requires explicit confirmation | Scenario 5 (diff printed, stdin read, only then CLI called) |
| `delete_entry` requires explicit confirmation | Scenario 6 + 7 |
| Cancellation is honored (LLM cannot bypass) | Scenario 6 ([VERIFY] line showing entry still present) |
| Diff display is human-readable, not raw JSON | Scenario 5 (`project: Web Redesign`, not `{id: ..., name: ..., code: ...}`) |
| Works with OpenAI-compatible local models (no API key) | Entire transcript — Qwen3-Coder-Next via llama.cpp :8080 |
| `harvest view --json` `null` shape handled correctly | Scenario 1, Scenario 7 post-delete verification |

## Reproducing this

```bash
# 1. Make sure llama-start is running
systemctl --user start llama-server

# 2. Set the harvest-agent env to point at it
export HARVEST_AGENT_BASE_URL=http://localhost:8080/v1
export HARVEST_AGENT_MODEL=Qwen3-Coder-Next

# 3. Make sure harvest CLI auth is set up
harvest view today --json   # should not error

# 4. Make sure the agent config exists
cp example_config.toml ~/.config/harvest-agent/config.toml
# (edit to add your own shortcuts if not Jane)

# 5. Run the agent
cd harvest-agent
pixi run agent
```

Or replay this exact test flow via the driver script at `/tmp/harvest-agent-smoke.py` (not committed; ad hoc).

## Test suite

```
$ pixi run test
59 passed, 1 warning in 0.55s
```

No mocks were bypassed for the smoke test — `tests/` still uses stubbed `harvest_cli.run` and stdin for determinism; this document is the real-world counterpart.
