"""Entrypoint for `python -m harvest_agent`."""

import sys

from harvest_agent.agent import run_repl

if __name__ == "__main__":
    sys.exit(run_repl())
