import json
import subprocess
from pathlib import Path

from julius.artifacts import ArtifactStore
from julius.claude_pair import (
    EXPECTED_ANSWER,
    EXPECTED_OUTPUT,
    FIXED_COMMAND,
    _artifact_evidence,
    gate_hook_event,
    run_claude_pair,
)


def _stream(command=FIXED_COMMAND, answer=EXPECTED_ANSWER, *, complete=True):
    events = [
        {"type": "assistant", "message": {"model": "claude-fixture", "content": [
            {"type": "tool_use", "id": "tool-1", "name": "Bash", "input": {"command": command}},
        ]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "tool-1", "content": "synthetic output"},
        ]}},
        {"type": "result", "subtype": "success" if complete else "error_max_turns",
         "is_error": not complete, "session_id": "fixture-session",
         "result": answer, "usage": {"input_tokens": 20, "output_tokens": 3,
                                   "cache_read_input_tokens": 2,
                                   "cache_creation_input_tokens": 1},
         "total_cost_usd": 0.01},
    ]
    return "\n".join(json.dumps(event) for event in events) + "\n"


def test_gate_only_allows_exact_fixed_command_and_recovery():
    assert gate_hook_event({"tool_name": "Bash", "tool_input": {"command": FIXED_COMMAND}}) is None
    assert gate_hook_event({"tool_name": "Bash", "tool_input": {"command": "pwd"}})
    assert gate_hook_event({"tool_name": "Bash", "tool_input": {"command": FIXED_COMMAND,
                                                                    "run_in_background": True}})
    assert gate_hook_event({"tool_name": "mcp__julius-recovery__restore_artifact",
                            "tool_input": {"artifactId": "12345678-1234-1234-1234-123456789abc"}}) is None
    assert gate_hook_event({"tool_name": "EndConversation", "tool_input": {}}) is None
    assert gate_hook_event({"tool_name": "mcp__other__tool", "tool_input": {}})


def test_gate_allows_fixed_command_at_most_once(tmp_path):
    event = {"tool_name": "Bash", "tool_input": {"command": FIXED_COMMAND}}
    marker = tmp_path / "used"
    assert gate_hook_event(event, once_file=marker) is None
    assert gate_hook_event(event, once_file=marker)


def test_pair_uses_isolated_projects_bounded_sessions_and_reports_fixture_totals(tmp_path):
    observed = []

    def fake_run(argv, **kwargs):
        observed.append({
            "argv": argv, "kwargs": kwargs,
            "settings": json.loads(Path(argv[2]).read_text()),
            "mcp": json.loads(Path(argv[4]).read_text()),
            "cwd": kwargs["cwd"],
        })
        return subprocess.CompletedProcess(argv, 0, _stream(), "")

    report = run_claude_pair(
        work_dir=tmp_path, project_id="synthetic", max_turns=2,
        max_budget_usd=0.05, timeout_seconds=4, model="haiku", runner=fake_run,
    )
    assert len(observed) == 2
    assert observed[0]["cwd"] != observed[1]["cwd"]
    assert observed[0]["kwargs"]["input"] == observed[1]["kwargs"]["input"]
    assert observed[0]["settings"]["hooks"].get("PostToolUse") is None
    assert observed[1]["settings"]["hooks"]["PostToolUse"]
    assert observed[0]["settings"]["hooks"]["PreToolUse"]
    assert set(observed[0]["mcp"]["mcpServers"]) == {"julius-recovery"}
    assert set(observed[1]["mcp"]["mcpServers"]) == {"julius-recovery"}
    for item in observed:
        argv = item["argv"]
        assert "--restricted" in argv
        assert argv[argv.index("--tools") + 1] == "Bash"
        assert "--strict-mcp-config" in argv
        assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
        assert argv[argv.index("--max-turns") + 1] == "2"
        assert argv[argv.index("--max-budget-usd") + 1] == "0.05"
        assert argv[argv.index("--model") + 1] == "haiku"
    for arm in report["arms"]:
        assert arm["complete"] is True
        assert arm["passed"] is True
        assert arm["usage"]["input_tokens"] == 20
        assert arm["cost_usd"] == 0.01
        assert arm["bash_requests"] == 1
        assert arm["bash_results"] == 1
        assert arm["latency_seconds"] >= 0
    assert report["conclusion"] == "descriptive_pair_only"


def test_failed_baseline_is_retained_and_safe_arm_still_runs(tmp_path):
    calls = 0

    def fake_run(argv, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return subprocess.CompletedProcess(argv, 0, _stream(answer="wrong"), "")

    report = run_claude_pair(
        work_dir=tmp_path, project_id="p", max_turns=1,
        max_budget_usd=0.02, timeout_seconds=1, runner=fake_run,
    )
    assert calls == 2
    assert report["arms"][0]["error"] == "timeout"
    assert report["arms"][0]["passed"] is False
    assert report["arms"][1]["complete"] is True
    assert report["arms"][1]["passed"] is False


def test_answer_needs_exact_command_and_tool_result(tmp_path):
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, _stream(command="pwd"), "")

    report = run_claude_pair(
        work_dir=tmp_path, project_id="p", max_turns=1,
        max_budget_usd=0.02, timeout_seconds=1, runner=fake_run,
    )
    assert all(not arm["passed"] for arm in report["arms"])
    assert all(arm["unexpected_tool_requests"] == 1 for arm in report["arms"])


def test_artifact_evidence_checks_restored_original_and_stream_id(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    matching = store.put("safe-project", EXPECTED_OUTPUT)
    normalized = store.put("safe-project", EXPECTED_OUTPUT.rstrip("\n"))
    other = store.put("safe-project", "different")
    evidence = _artifact_evidence(tmp_path, "safe-project", matching["id"])
    by_id = {item["artifact_id"]: item for item in evidence}
    assert by_id[matching["id"]]["original_matches_fixed_output"] is True
    assert by_id[matching["id"]]["original_matches_without_final_newline"] is False
    assert by_id[matching["id"]]["id_observed_in_stream"] is True
    assert by_id[normalized["id"]]["original_matches_fixed_output"] is False
    assert by_id[normalized["id"]]["original_matches_without_final_newline"] is True
    assert by_id[other["id"]]["original_matches_fixed_output"] is False
    assert _artifact_evidence(tmp_path, "another-project", matching["id"]) == []
