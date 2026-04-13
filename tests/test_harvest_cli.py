import subprocess
from unittest.mock import MagicMock

import pytest

from harvest_agent import harvest_cli


def _mock_completed(stdout="", stderr="", returncode=0):
    m = MagicMock(spec=subprocess.CompletedProcess)
    m.stdout = stdout
    m.stderr = stderr
    m.returncode = returncode
    return m


def test_run_returns_stdout_on_success(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: _mock_completed(stdout='{"ok": true}', returncode=0),
    )
    result = harvest_cli.run(["view", "today", "--json"])
    assert result["ok"] is True
    assert result["stdout"] == '{"ok": true}'
    assert result["returncode"] == 0


def test_run_returns_error_on_nonzero(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: _mock_completed(stderr="auth failed", returncode=1),
    )
    result = harvest_cli.run(["view", "today"])
    assert result["ok"] is False
    assert result["returncode"] == 1
    assert "auth failed" in result["stderr"]


def test_run_scrubs_token_pattern_from_stderr(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: _mock_completed(stderr="error: token=sk-abc123def456 invalid", returncode=1),
    )
    result = harvest_cli.run(["view", "today"])
    assert "sk-abc123def456" not in result["stderr"]
    assert "[REDACTED]" in result["stderr"]


def test_run_scrubs_bearer_pattern(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: _mock_completed(stderr="Authorization: Bearer abcdef123456 failed", returncode=1),
    )
    result = harvest_cli.run(["view", "today"])
    assert "abcdef123456" not in result["stderr"]
    assert "[REDACTED]" in result["stderr"]


def test_run_passes_command_through_argv(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _mock_completed(stdout="ok")

    monkeypatch.setattr(subprocess, "run", fake_run)
    harvest_cli.run(["view", "today", "--json"])
    assert captured["cmd"] == ["harvest", "view", "today", "--json"]
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["text"] is True
