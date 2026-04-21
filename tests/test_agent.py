"""Smoke tests for agent construction and tool registration.

Uses PydanticAI's TestModel to avoid hitting a real LLM provider.
"""

from datetime import date
from pathlib import Path
from unittest.mock import patch

from pydantic_ai.models.test import TestModel

from harvest_agent import tools
from harvest_agent.agent import _build_agent
from harvest_agent.config import Config
from harvest_agent.project_index import ProjectInfo


EXPECTED_TOOLS = {
    "view_today",
    "view_week",
    "view_range",
    "list_projects",
    "list_tasks",
    "status",
    "log_time",
    "start_timer",
    "stop_timer",
    "edit_entry",
    "delete_entry",
}


def test_agent_constructs_with_empty_config():
    with patch("harvest_agent.agent.build_project_index", return_value={}), \
         patch("harvest_agent.agent.build_recent_pairs", return_value=set()):
        agent = _build_agent(Config(), model=TestModel(call_tools=[]))
    assert agent is not None


def test_agent_registers_all_expected_tools():
    # call_tools=[] sends schemas to the model but skips tool execution,
    # which avoids TTY prompts from confirm_action during tests.
    test_model = TestModel(call_tools=[])
    with patch("harvest_agent.agent.build_project_index", return_value={}), \
         patch("harvest_agent.agent.build_recent_pairs", return_value=set()):
        agent = _build_agent(Config(), model=test_model)
    with agent.override(model=test_model):
        # A trivial run forces tool schemas to be sent to the model.
        agent.run_sync("hello")
    registered = {t.name for t in test_model.last_model_request_parameters.function_tools}
    missing = EXPECTED_TOOLS - registered
    extra = registered - EXPECTED_TOOLS
    assert not missing, f"Missing tools: {missing}"
    assert not extra, f"Unexpected tools: {extra}"


def test_agent_run_completes_without_real_provider():
    with patch("harvest_agent.agent.build_project_index", return_value={}), \
         patch("harvest_agent.agent.build_recent_pairs", return_value=set()):
        agent = _build_agent(Config(), model=TestModel(call_tools=[]))
    with agent.override(model=TestModel(call_tools=[])):
        result = agent.run_sync("hello")
    # TestModel returns a stub response; we only care that the run completed.
    assert result.output is not None


def test_agent_build_passes_project_index_to_tools_and_prompt():
    """_build_agent should fetch the project index and install it on _ToolContext."""
    fake_index = {
        "web redesign": ProjectInfo(canonical_name="Web Redesign", tasks={"programming": "Programming"}),
    }
    with patch("harvest_agent.agent.build_project_index", return_value=fake_index), \
         patch("harvest_agent.agent.build_recent_pairs", return_value=set()):
        agent = _build_agent(
            Config(),
            model=TestModel(call_tools=[]),
            today=date(2026, 4, 8),
        )
    # Tools module sees the fetched index
    assert tools._context.project_index == fake_index
    tools.configure()  # reset
    assert agent is not None


def test_agent_build_handles_failed_project_index_fetch():
    """When the index builder returns {}, the agent still constructs."""
    with patch("harvest_agent.agent.build_project_index", return_value={}), \
         patch("harvest_agent.agent.build_recent_pairs", return_value=set()):
        agent = _build_agent(Config(), model=TestModel(call_tools=[]), today=date(2026, 4, 8))
    assert agent is not None
    assert tools._context.project_index == {}
    tools.configure()


def test_agent_build_threads_config_path_into_system_prompt():
    """_build_agent should pass config_path through to build_system_prompt
    so the rendered system prompt contains the preferences-file section."""
    fake_path = Path("/tmp/fake-harvest-agent/config.toml")
    with patch("harvest_agent.agent.build_project_index", return_value={}), \
         patch("harvest_agent.agent.build_recent_pairs", return_value=set()):
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
