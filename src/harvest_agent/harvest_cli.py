"""Subprocess wrapper for the harvest Go CLI.

This is the ONLY module in the codebase that calls subprocess. All tools go
through `run()`. Stderr is scrubbed for common credential patterns before being
returned, as defense in depth — the harvest CLI shouldn't print secrets, but we
prefer to not find out the hard way.
"""

import re
import subprocess
from typing import Any

# Patterns that look like credentials, scrubbed from stderr before display.
_SECRET_PATTERNS = [
    re.compile(r"(token\s*[=:]\s*)\S+", re.IGNORECASE),
    re.compile(r"(bearer\s+)\S+", re.IGNORECASE),
    re.compile(r"(authorization\s*[=:]\s*)\S+", re.IGNORECASE),
    re.compile(r"(api[_-]?key\s*[=:]\s*)\S+", re.IGNORECASE),
]


def _scrub(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(r"\1[REDACTED]", text)
    return text


def run(args: list[str], timeout: int = 30) -> dict[str, Any]:
    """Invoke `harvest <args>` and return a structured result.

    Args:
        args: subcommand and flags, e.g. ["view", "today", "--json"]
        timeout: subprocess timeout in seconds.

    Returns:
        A dict with keys:
            ok: bool — True iff returncode == 0
            returncode: int
            stdout: str — captured stdout
            stderr: str — captured stderr, with secret patterns redacted
    """
    cmd = ["harvest", *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": f"harvest CLI timed out after {timeout}s",
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "returncode": -1,
            "stdout": "",
            "stderr": "harvest CLI not found on PATH. Install: `go install github.com/Adam-D-Lewis/harvest-go-cli/cmd/harvest@v0.3.0`",
        }
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": _scrub(proc.stderr),
    }
