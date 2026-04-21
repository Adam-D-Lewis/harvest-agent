"""PydanticAI agent + REPL loop."""

import os
import sys
from datetime import date
from pathlib import Path

from pydantic_ai import Agent

from harvest_agent import tools
from harvest_agent.config import Config, ConfigError, default_config_path, load_config
from harvest_agent.day_diff import fetch_today_entries, format_changes
from harvest_agent.project_index import build_project_index
from harvest_agent.prompt import build_system_prompt
from harvest_agent.recent_usage import build_recent_pairs

DEFAULT_MODEL = "anthropic:claude-sonnet-4-6"


def _resolve_model():
    """Pick a model based on environment variables.

    All env vars are prefixed `HARVEST_AGENT_` to avoid clashing with other
    tools (`OPENAI_API_KEY` in particular is shared by many tools and we
    don't want to implicitly inherit it).

    Precedence:
    1. If `HARVEST_AGENT_BASE_URL` is set, assume an OpenAI-compatible
       endpoint (llama.cpp, Ollama, LM Studio, etc.) and build an
       `OpenAIChatModel` pointed at it. The model name comes from
       `HARVEST_AGENT_MODEL` (required in this mode) and the API key from
       `HARVEST_AGENT_API_KEY` or defaults to a placeholder (most local
       servers ignore it).
    2. Otherwise, use `HARVEST_AGENT_MODEL` as a PydanticAI model string
       (e.g. "anthropic:claude-sonnet-4-6"), defaulting to DEFAULT_MODEL.

    Note: the Anthropic provider reads `ANTHROPIC_API_KEY` directly from the
    environment — we don't rename that one because it lives inside
    PydanticAI, not our code.
    """
    base_url = os.environ.get("HARVEST_AGENT_BASE_URL")
    if base_url:
        # Imports are local because the OpenAI provider is only needed in
        # this branch; the default anthropic path stays import-light.
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        model_name = os.environ.get("HARVEST_AGENT_MODEL")
        if not model_name:
            raise RuntimeError(
                "HARVEST_AGENT_BASE_URL is set but HARVEST_AGENT_MODEL is not. "
                "Set HARVEST_AGENT_MODEL to the model name exposed by the endpoint."
            )
        api_key = os.environ.get("HARVEST_AGENT_API_KEY", "not-needed")
        return OpenAIChatModel(
            model_name,
            provider=OpenAIProvider(base_url=base_url, api_key=api_key),
        )
    return os.environ.get("HARVEST_AGENT_MODEL", DEFAULT_MODEL)


def _describe_model(model) -> str:
    """Human-readable description of the model for the startup banner."""
    if isinstance(model, str):
        return model
    # For OpenAIChatModel, show the model name + base URL.
    model_name = getattr(model, "model_name", None) or getattr(model, "_model_name", None) or type(model).__name__
    base_url = os.environ.get("HARVEST_AGENT_BASE_URL", "<unknown>")
    return f"{model_name} @ {base_url}"


def _format_debug_messages(messages) -> str:
    """Format new messages from a single agent run for debug display.

    We surface tool calls and tool returns — these are the only "hidden" steps
    in a normal (non-reasoning) model run. The final assistant text is shown
    separately as `result.output`, so we skip TextParts to avoid duplication.

    Tool return content can be huge (entire harvest JSON dumps); truncate it
    to a few hundred chars so the debug stream stays scannable.
    """
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        ToolCallPart,
        ToolReturnPart,
    )

    lines: list[str] = []
    for msg in messages:
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart):
                    lines.append(f"  [tool call]   {part.tool_name}({part.args})")
        elif isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    content = repr(part.content)
                    if len(content) > 400:
                        content = content[:400] + "...[truncated]"
                    lines.append(f"  [tool return] {part.tool_name}: {content}")
    return "\n".join(lines)


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
    # Fetch recent (project, task) pairs so log_time can warn when the user
    # logs to a pair they haven't used in the configured window. Empty set on
    # fetch failure disables the warning (same "fail open" pattern as the
    # project index).
    recent_pairs = build_recent_pairs(cfg.behavior.unusual_project_window_days, today)
    # Install config-derived state into the tools module so individual tool
    # functions can resolve shortcuts, parse relative dates, and validate
    # project/task names against the same data the system prompt saw.
    tools.configure(
        shortcuts=cfg.shortcut,
        today=today,
        project_index=project_index,
        recent_pairs=recent_pairs,
        recent_window_days=cfg.behavior.unusual_project_window_days,
    )
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


def run_repl() -> int:
    """Start the REPL. Returns a process exit code."""
    config_path = default_config_path()
    if not config_path.exists():
        print(f"No config file found at {config_path}.")
        print("Harvest Agent needs a config file with your shortcuts and preferences.")
        print()
        try:
            response = input("Create a starter config now? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if response in ("", "y", "yes"):
            from harvest_agent.config import scaffold_config
            try:
                scaffold_config(config_path)
            except ConfigError as e:
                print(f"Could not create config: {e}", file=sys.stderr)
                return 1
            print(f"\nWrote a starter config to {config_path}.")
            print("Edit it to add your shortcuts and recurring meetings, then re-run the agent.")
            return 0
        return 1

    try:
        cfg = load_config(config_path)
    except ConfigError as e:
        print(f"Could not load config: {e}", file=sys.stderr)
        return 2

    agent = _build_agent(cfg, config_path=config_path)
    debug = bool(os.environ.get("HARVEST_AGENT_DEBUG"))
    print(f"Harvest Agent ready (model={_describe_model(agent.model)}, config={config_path})")
    if debug:
        print("[debug mode on — tool calls and returns will be printed]")
    print("Type your request, or 'quit' to exit.\n")

    message_history: list = []
    while True:
        try:
            user_input = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            return 0
        if not user_input or user_input.lower() in ("quit", "exit", "q"):
            print("Bye!")
            return 0

        # Snapshot today's entries so we can show a deterministic before/after
        # summary after the agent's turn. Lives in the REPL layer (not prompt-
        # driven) so even weak models can't bypass it.
        before_today = fetch_today_entries()
        result = agent.run_sync(user_input, message_history=message_history)
        if debug:
            debug_lines = _format_debug_messages(result.new_messages())
            if debug_lines:
                print("\n[debug]")
                print(debug_lines)
        message_history = result.all_messages()
        after_today = fetch_today_entries()
        changes = format_changes(before_today, after_today)
        if changes:
            print(f"\n{changes}")
        print(f"\nAgent> {result.output}\n")
