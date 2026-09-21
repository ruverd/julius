import json
import hashlib
import subprocess
from pathlib import Path

from julius.claude_pair import PILOT_TASKS
from julius.claude_pilot import run_claude_pilot


def _stream(command: str, answer: str) -> str:
    events = [
        {"type": "assistant", "message": {"model": "fixture-model", "content": [
            {"type": "tool_use", "id": "one", "name": "Bash", "input": {"command": command}},
        ]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "one", "content": "fixture output"},
        ]}},
        {"type": "result", "subtype": "success", "is_error": False,
         "result": answer, "session_id": "fixture-session",
         "usage": {"input_tokens": 20, "output_tokens": 3},
         "total_cost_usd": 0.01},
    ]
    return "\n".join(json.dumps(event) for event in events) + "\n"


def test_pilot_retains_every_task_and_randomized_order(tmp_path):
    seen = []

    def fake_run(argv, **kwargs):
        task = next(task for task in PILOT_TASKS if task["prompt"] == kwargs["input"])
        run_dir = tmp_path / next(path.name for path in tmp_path.iterdir()
                                  if path.name.startswith("claude-pilot-"))
        registration = json.loads((run_dir / "registration.json").read_text())
        partial = json.loads((run_dir / "report.json").read_text())
        assert len(registration["order"]) == 12
        assert len(partial["attempts"]) == len(seen)
        assert partial["complete"] is False
        seen.append((task["id"], argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, _stream(task["command"], task["answer"]), "")

    report = run_claude_pilot(
        work_dir=tmp_path, project_id="fixture", max_turns=2,
        max_budget_usd=0.05, timeout_seconds=5, order_seed=17,
        client_version="fixture-1", cache_state="fresh-profile", runner=fake_run,
    )
    assert len(seen) == len(PILOT_TASKS) * 2
    assert all(attempt["passed"] for attempt in report["attempts"])
    assert all(attempt["result_subtype"] == "success" for attempt in report["attempts"])
    assert report["measurement_scope"] == "client_reported_session_totals_only"
    assert report["conclusion"] == "descriptive_pilot_only"
    assert report["complete"] is True
    canonical = [{key: task[key] for key in
                  ("id", "language", "command", "output", "answer", "prompt")}
                 for task in PILOT_TASKS]
    expected_hash = hashlib.sha256(json.dumps(canonical, sort_keys=True,
                                               separators=(",", ":"),
                                               ensure_ascii=False).encode()).hexdigest()
    assert report["corpus_sha256"] == expected_hash
    assert [entry["execution_sequence"] for entry in report["order"]] == list(range(1, 13))
    assert [a["execution_sequence"] for a in report["attempts"]] == list(range(1, 13))
    assert all(a["client_version"] == "fixture-1" and a["cache_state"] == "fresh-profile"
               for a in report["attempts"])
    assert all(a["task_sha256"] == next(t["task_sha256"] for t in report["tasks"]
                                         if t["id"] == a["task_id"])
               for a in report["attempts"])
    assert {task["language"] for task in report["tasks"]} == {"en", "pt"}
    assert {task["context_kind"] for task in report["tasks"]} == {"compact", "repetitive"}
    assert json.loads((Path(report["run_dir"]) / "report.json").read_text())["order"] == report["order"]
    for task in PILOT_TASKS:
        attempts = [a for a in report["attempts"] if a["task_id"] == task["id"]]
        assert {a["arm"] for a in attempts} == {"baseline", "safe_hook"}
        assert len({a["project_id"] for a in attempts}) == 2
    for _, argv, kwargs in seen:
        assert argv[argv.index("--max-turns") + 1] == "2"
        assert argv[argv.index("--max-budget-usd") + 1] == "0.05"
        assert kwargs["timeout"] == 5


def test_pilot_keeps_timeout_and_wrong_answer(tmp_path):
    calls = 0

    def fake_run(argv, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        task = next(task for task in PILOT_TASKS if task["prompt"] == kwargs["input"])
        return subprocess.CompletedProcess(argv, 0, _stream(task["command"], "wrong"), "")

    report = run_claude_pilot(
        work_dir=tmp_path, project_id="fixture", max_turns=1,
        max_budget_usd=0.02, timeout_seconds=1, order_seed=0, runner=fake_run,
    )
    assert len(report["attempts"]) == len(PILOT_TASKS) * 2
    assert report["attempts"][0]["error"] == "timeout"
    assert all(not attempt["passed"] for attempt in report["attempts"])
    assert report["client_version"] is None
    assert report["cache_state"] is None


def test_pilot_rejects_invalid_limits_before_launch(tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("launched")

    try:
        run_claude_pilot(work_dir=tmp_path, project_id="p", max_turns=0,
                         max_budget_usd=1, timeout_seconds=1, order_seed=1,
                         runner=forbidden)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
