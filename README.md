# Harvest Agent

A PydanticAI-based REPL agent that wraps the [`harvest`](https://github.com/Adam-D-Lewis/harvest-go-cli) CLI for time tracking.

**Safe by default:**
- Read and log freely.
- `edit` and `delete` always pause for an explicit confirmation prompt with a before/after diff. The LLM cannot bypass this gate — it lives in Python code, not the system prompt.

## Prerequisites

1. Install the harvest CLI:
   ```bash
   go install github.com/Adam-D-Lewis/harvest-go-cli/cmd/harvest@v0.3.0
   ```
2. Configure harvest credentials in `~/.config/harvest/.env` (see harvest CLI docs).
3. Set your LLM provider key:
   ```bash
   export ANTHROPIC_API_KEY=sk-ant-...
   ```

## Install

```bash
cd harvest-agent
pixi install
```

## First run (onboarding)

```bash
pixi run agent
```

The agent will detect that you don't have a config yet and offer to scaffold one at `~/.config/harvest-agent/config.toml`. Edit it to add your shortcuts and recurring meetings, then re-run.

See `example_config.toml` for a fully-populated example.

## Configuration

The config lives at `~/.config/harvest-agent/config.toml` (or `$XDG_CONFIG_HOME/harvest-agent/config.toml`).

| Section | Purpose |
|---|---|
| `[user]` | Optional user name, surfaced in the system prompt. |
| `[[shortcut]]` | Map a short name to a project + task. The agent recognizes these in your messages. |
| `[[recurring_meeting]]` | Standing meetings the agent uses when auto-splitting hours. |
| `[behavior]` | Toggles + free-form notes that go directly into the system prompt. |

## Tools the agent can call

| Category | Tool | Wraps |
|---|---|---|
| Read | `view_today`, `view_week`, `view_range`, `list_projects`, `list_tasks`, `status` | `harvest view ...`, `harvest list ...`, `harvest status` |
| Additive | `log_time`, `start_timer`, `stop_timer` | `harvest log`, `harvest start`, `harvest stop` |
| Destructive (confirm) | `edit_entry`, `delete_entry` | `harvest edit`, `harvest delete` |

## Security

- The agent process never reads `HARVEST_TOKEN` or `~/.config/harvest/.env`. Credentials reach the harvest CLI through the parent shell environment, which the agent inherits but never inspects.
- `harvest_cli.run` scrubs known secret patterns from stderr before returning to the LLM (defense in depth — the harvest CLI shouldn't print secrets, but we don't want to find out the hard way).
- The system prompt and tool docstrings never reference credentials. The LLM has no concept that secrets exist.

## Why a synchronous confirm gate (not Pydantic AI deferred tools)?

PydanticAI has a native [Deferred Tools](https://ai.pydantic.dev/deferred-tools/) pattern for human-in-the-loop approval. We deliberately use a synchronous in-tool prompt instead because:

1. The agent is REPL-only — the user is sitting at the terminal when destructive ops happen, so async deferral buys nothing.
2. The synchronous helper has zero coupling to PydanticAI internals, so the safety gate stays portable if we ever change frameworks.
3. If a non-REPL frontend is ever added (Slack bot, web UI), migrating to deferred tools at that point is a contained refactor.

## Development

```bash
pixi run test           # run pytest
pixi run agent          # start the REPL
```

Override the model:
```bash
HARVEST_AGENT_MODEL=anthropic:claude-opus-4-6 pixi run agent
```

Use a local OpenAI-compatible endpoint (llama.cpp, Ollama, LM Studio, vLLM, etc.):
```bash
export HARVEST_AGENT_BASE_URL=http://localhost:8080/v1
export HARVEST_AGENT_MODEL=Qwen3-Coder-Next      # whatever model the server exposes
pixi run agent
```
When `HARVEST_AGENT_BASE_URL` is set, the agent builds an `OpenAIChatModel` pointed at that endpoint instead of using the PydanticAI provider string. `HARVEST_AGENT_API_KEY` is optional (most local servers ignore it).

All env vars the harvest-agent reads are prefixed `HARVEST_AGENT_` to avoid clashing with other tools — notably we don't implicitly inherit `OPENAI_API_KEY` since it's shared across many things. The one exception is `ANTHROPIC_API_KEY`, which PydanticAI's Anthropic provider reads directly.
