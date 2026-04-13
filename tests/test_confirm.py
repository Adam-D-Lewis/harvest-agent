import io

import pytest

from harvest_agent import confirm


def test_confirm_returns_true_on_y(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    result = confirm.confirm_action(
        title="Delete entry",
        before={"hours": 4.5, "notes": "standup"},
        after=None,
    )
    assert result is True
    out = capsys.readouterr().out
    assert "Delete entry" in out
    assert "4.5" in out


def test_confirm_returns_true_on_yes(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("yes\n"))
    assert confirm.confirm_action("x", {"a": 1}, {"a": 2}) is True


def test_confirm_returns_false_on_n(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))
    assert confirm.confirm_action("x", {"a": 1}, {"a": 2}) is False


def test_confirm_returns_false_on_empty(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("\n"))
    assert confirm.confirm_action("x", {"a": 1}, {"a": 2}) is False


def test_confirm_returns_false_on_anything_else(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("maybe\n"))
    assert confirm.confirm_action("x", {"a": 1}, {"a": 2}) is False


def test_confirm_diff_shows_changed_field(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    confirm.confirm_action(
        "Edit entry",
        before={"hours": 4.5, "notes": "standup"},
        after={"hours": 2.5, "notes": "standup"},
    )
    out = capsys.readouterr().out
    assert "hours" in out
    assert "4.5" in out and "2.5" in out


def test_confirm_delete_shows_no_after(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    confirm.confirm_action(
        "Delete entry",
        before={"id": 99, "hours": 1.0, "notes": "test"},
        after=None,
    )
    out = capsys.readouterr().out
    assert "Delete entry" in out
    assert "99" in out
