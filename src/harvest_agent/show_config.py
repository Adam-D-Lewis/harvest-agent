"""Print the active harvest-agent configuration.

Displays the resolved config file path, the harvest-agent environment
variables, the model that would be used, and the raw contents of the config
file. Useful for debugging "is my override taking effect?" questions.

Run with: `pixi run show-config` (or `python -m harvest_agent.show_config`).
"""

import os
import sys

from harvest_agent.agent import _describe_model, _resolve_model
from harvest_agent.config import default_config_path

_RELEVANT_ENV_VARS = (
    "HARVEST_AGENT_BASE_URL",
    "HARVEST_AGENT_MODEL",
    "HARVEST_AGENT_API_KEY",
    "HARVEST_AGENT_DEBUG",
    "ANTHROPIC_API_KEY",
    "XDG_CONFIG_HOME",
)


def _mask(name: str, value: str) -> str:
    """Mask anything that looks like a secret so it isn't echoed verbatim."""
    if "KEY" in name or "TOKEN" in name or "SECRET" in name:
        if not value:
            return ""
        return f"<set, {len(value)} chars>"
    return value


def main() -> int:
    config_path = default_config_path()

    print("=== harvest-agent config ===")
    print(f"config path: {config_path}")
    print(f"exists:      {config_path.exists()}")

    print()
    print("--- environment ---")
    for name in _RELEVANT_ENV_VARS:
        raw = os.environ.get(name)
        if raw is None:
            print(f"  {name}: <unset>")
        else:
            print(f"  {name}: {_mask(name, raw)}")

    print()
    print("--- resolved model ---")
    try:
        model = _resolve_model()
        print(f"  {_describe_model(model)}")
    except Exception as e:
        print(f"  <error resolving model: {e}>")

    print()
    print("--- config file contents ---")
    if not config_path.exists():
        print("  (no config file — run `pixi run agent` to scaffold one)")
        return 0
    try:
        print(config_path.read_text())
    except OSError as e:
        print(f"  <error reading config: {e}>", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
