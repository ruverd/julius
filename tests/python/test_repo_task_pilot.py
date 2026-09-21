import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from julius.repo_task_pilot import CORPUS_PATH, run_repo_task_pilot


COMMAND = "cat README.md notes.py store.py routes.py"


def stream(answer, command=COMMAND, *, success=True):
    events = [
        {"type": "assistant", "message": {"model": "fixture-model", "content": [
            {"type": "tool_use", "id": "tool-1", "name": "Bash", "input": {"command": command}},
        ]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "tool-1", "content": "frozen files"},
        ]}},
        {"type": "result", "subtype": "success" if success else "error_max_turns",
         "is_error": not success, "session_id": "fixture-session", "result": answer,
         "usage": {"input_tokens": 12, "output_tokens": 4}, "total_cost_usd": 0.02},
    ]
    return "\n".join(json.dumps(event) for event in events) + "\n"


def test_paired_run_registers_corpus_before_calls_and_isolates_arms(tmp_path):
    seen = []

    def fake(argv, **kwargs):
        run_dir = next(tmp_path.glob("repo-task-pilot-*"))
        assert (run_dir / "corpus-registration.json").exists()
        settings = json.loads(Path(argv[2]).read_text())
        seen.append((argv, kwargs, settings))
        return subprocess.CompletedProcess(argv, 0, stream("store.py:load"), "")

    report = run_repo_task_pilot(
        work_dir=tmp_path, project_id="fixture", max_turns=2,
        max_budget_usd=0.05, timeout_seconds=3, task_ids=("bug-en",), runner=fake,
    )
    assert len(seen) == 2
    assert seen[0][1]["cwd"] != seen[1][1]["cwd"]
    assert seen[0][2]["hooks"].get("PostToolUse") is None
    assert seen[1][2]["hooks"]["PostToolUse"]
    for argv, kwargs, settings in seen:
        assert "--restricted" in argv
        assert argv[argv.index("--allowedTools") + 1] == f"Bash({COMMAND})"
        assert argv[argv.index("--max-turns") + 1] == "2"
        assert argv[argv.index("--max-budget-usd") + 1] == "0.05"
        assert settings["hooks"]["PreToolUse"]
        assert kwargs["input"].find(COMMAND) >= 0
    assert all(arm["passed"] for arm in report["arms"])
    assert all(arm["cost_usd"] == 0.02 for arm in report["arms"])
    assert (Path(report["run_dir"]) / "report.json").exists()


def test_failure_preserves_usage_and_continues(tmp_path):
    calls = 0

    def fake(argv, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(argv, 1, stream("wrong", success=False), "failure")
        return subprocess.CompletedProcess(argv, 0, stream("wrong"), "")

    report = run_repo_task_pilot(
        work_dir=tmp_path, project_id="fixture", max_turns=1,
        max_budget_usd=0.01, timeout_seconds=1, task_ids=("bug-pt",), runner=fake,
    )
    assert calls == 2
    assert all(not arm["passed"] for arm in report["arms"])
    assert report["arms"][0]["usage"]["input_tokens"] == 12
    assert report["arms"][0]["cost_usd"] == 0.02
    assert report["arms"][0]["error"] == "client_error_or_incomplete"


def test_unexpected_command_cannot_pass(tmp_path):
    def fake(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stream("routes.py:post_notes", "pwd"), "")

    report = run_repo_task_pilot(
        work_dir=tmp_path, project_id="fixture", max_turns=1,
        max_budget_usd=0.01, timeout_seconds=1, task_ids=("flow-en",), runner=fake,
    )
    assert all(not arm["passed"] for arm in report["arms"])
    assert all(arm["unexpected_tool_requests"] == 1 for arm in report["arms"])


def test_rejects_invalid_limits_and_task_ids(tmp_path):
    base = dict(work_dir=tmp_path, project_id="fixture", max_turns=1,
                max_budget_usd=0.01, timeout_seconds=1)
    with pytest.raises(ValueError):
        run_repo_task_pilot(**(base | {"task_ids": ("unknown",)}))
    with pytest.raises(ValueError):
        run_repo_task_pilot(**(base | {"max_turns": 0}))


def test_frozen_fixture_matches_packaged_data():
    fixture = Path(__file__).resolve().parents[1] / "fixtures/repo-task-pilot/tasks.json"
    assert CORPUS_PATH.read_bytes() == fixture.read_bytes()


def test_corpus_loads_from_installed_wheel_layout(tmp_path):
    wheels = sorted((Path(__file__).resolve().parents[2] / "dist/wheels").glob("julius_local-*.whl"))
    if not wheels:
        pytest.skip("Build a wheel with sh scripts/dev.sh build for installed-layout test")
    target = tmp_path / "site-packages"
    target.mkdir()
    with zipfile.ZipFile(wheels[-1]) as archive:
        archive.extractall(target)
    script = (
        "import julius.repo_task_pilot as p; "
        "raw, data = p._corpus(p.CORPUS_PATH); "
        "assert len(data['tasks']) == 4; "
        "print(p.CORPUS_PATH)"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path,
        env={"PYTHONPATH": str(target)}, text=True, capture_output=True, check=True,
    )
    assert str(target) in result.stdout
