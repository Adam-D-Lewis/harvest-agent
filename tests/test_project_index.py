import json
from unittest.mock import patch

from harvest_agent.project_index import ProjectInfo, ProjectIndex, build_project_index


def test_project_info_holds_canonical_name_and_tasks():
    info = ProjectInfo(canonical_name="Web Redesign", tasks={"programming": "Programming"})
    assert info.canonical_name == "Web Redesign"
    assert info.tasks["programming"] == "Programming"


def test_project_index_is_a_dict_alias():
    # ProjectIndex is just `dict[str, ProjectInfo]` — verify it behaves as one.
    idx: ProjectIndex = {"web redesign": ProjectInfo(canonical_name="Web Redesign", tasks={})}
    assert idx["web redesign"].canonical_name == "Web Redesign"


def _ok(stdout: str) -> dict:
    return {"ok": True, "returncode": 0, "stdout": stdout, "stderr": ""}


def _project_assignment(project_id, project_name, tasks):
    """Build a fake harvest ProjectAssignment with nested task_assignments."""
    return {
        "id": project_id * 10,  # assignment id, distinct from project id
        "is_active": True,
        "project": {"id": project_id, "name": project_name, "code": ""},
        "client": {"id": 1, "name": "C"},
        "task_assignments": [
            {
                "id": 9000 + t_id,
                "is_active": True,
                "task": {"id": t_id, "name": t_name},
            }
            for t_id, t_name in tasks
        ],
    }


def test_build_project_index_happy_path():
    payload = json.dumps([
        _project_assignment(1, "Web Redesign", [(10, "Programming"), (11, "Meetings / Standups")]),
        _project_assignment(2, "Mobile App v2", [(20, "Backend API")]),
    ])
    with patch("harvest_agent.project_index.harvest_cli.run", return_value=_ok(payload)) as m:
        idx = build_project_index()

    m.assert_called_once_with(["list", "projects", "--json"])
    assert set(idx.keys()) == {"web redesign", "mobile app v2"}

    dl = idx["web redesign"]
    assert dl.canonical_name == "Web Redesign"
    assert dl.tasks == {
        "programming": "Programming",
        "meetings / standups": "Meetings / Standups",
    }

    mobile = idx["mobile app v2"]
    assert mobile.canonical_name == "Mobile App v2"
    assert mobile.tasks == {"backend api": "Backend API"}


def _err(stderr: str) -> dict:
    return {"ok": False, "returncode": 1, "stdout": "", "stderr": stderr}


def test_build_project_index_returns_empty_when_cli_fails(capsys):
    with patch("harvest_agent.project_index.harvest_cli.run", return_value=_err("auth failed")):
        idx = build_project_index()
    assert idx == {}
    captured = capsys.readouterr()
    assert "validation disabled" in captured.err
    assert "auth failed" in captured.err


def test_build_project_index_returns_empty_when_payload_is_invalid_json(capsys):
    with patch("harvest_agent.project_index.harvest_cli.run", return_value=_ok("not json {")):
        idx = build_project_index()
    assert idx == {}
    captured = capsys.readouterr()
    assert "valid JSON" in captured.err


def test_build_project_index_returns_empty_when_payload_is_not_a_list():
    with patch("harvest_agent.project_index.harvest_cli.run", return_value=_ok('{"oops": true}')):
        idx = build_project_index()
    assert idx == {}


def test_build_project_index_skips_assignments_with_missing_fields():
    payload = json.dumps([
        {"project": {"id": 1, "name": "Good"}, "task_assignments": []},
        {"project": {"id": 2}},                    # missing name
        {"project": "not a dict"},                 # malformed
        "totally bogus",                           # not even a dict
        {"project": {"id": 3, "name": "Also Good"},
         "task_assignments": [
             {"task": {"id": 30, "name": "Real Task"}},
             {"task": {"id": 31}},                 # missing name → skipped
             {"not_a_task": True},                 # malformed → skipped
         ]},
    ])
    with patch("harvest_agent.project_index.harvest_cli.run", return_value=_ok(payload)):
        idx = build_project_index()
    assert set(idx.keys()) == {"good", "also good"}
    assert idx["good"].tasks == {}
    assert idx["also good"].tasks == {"real task": "Real Task"}
