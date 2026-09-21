import json

import pytest

import julius.cli as cli
from julius.sdk import Julius


def test_claude_runner_requires_recovery_for_safe_profile(tmp_path, monkeypatch):
    calls = []

    def launch(**arguments):
        calls.append(arguments)
        return 0

    monkeypatch.setattr(cli, "run_claude", launch)
    common = ["run", "--agent", "claude", "--project", "p", "--data-dir", str(tmp_path)]
    assert cli.run(common) == 0
    assert calls[0]["enable_safe_hook"] is False
    with pytest.raises(ValueError, match="requires --recovery-verified"):
        cli.run([*common, "--profile", "safe"])
    assert cli.run([*common, "--profile", "safe", "--recovery-verified"]) == 0
    assert calls[1]["enable_safe_hook"] is True
    assert calls[1]["recovery_verified"] is True
    assert cli.run([*common, "--task", "DEV-123"]) == 0
    assert calls[2]["task_id"] == "DEV-123"


def test_lmstudio_model_selection_is_explicit(monkeypatch, capsys):
    monkeypatch.setattr(cli, "discover_lmstudio", lambda endpoint: {
        "endpoint": endpoint, "models": [], "error": None,
    })
    assert cli.run(["models", "list", "--runtime", "lmstudio"]) == 0
    assert json.loads(capsys.readouterr().out)["endpoint"] == "http://127.0.0.1:1234"


def test_claude_print_records_one_client_session_delta_without_cache_double_count(
    tmp_path, monkeypatch, capsys
):
    source = tmp_path / "prompt.txt"
    source.write_text("private synthetic prompt")

    def fake_print(**kwargs):
        assert kwargs["prompt"] == "private synthetic prompt"
        assert kwargs["max_budget_usd"] == 0.1
        return {
            "scope": "claude_session_delta", "complete": True, "error": None,
            "exit_code": 0, "session_id": "session", "actual_model": "claude-fixture",
            "observed_models": ["claude-fixture"],
            "usage": {"input_tokens": 10, "cache_read_input_tokens": 20,
                      "cache_creation_input_tokens": 30, "output_tokens": 5},
            "cost_usd": 0.02, "cost_scope": "client_reported_session_total",
            "output": "done",
        }

    monkeypatch.setattr(cli, "run_claude_print", fake_print)
    assert cli.run([
        "run", "--agent", "claude", "--project", "p", "--task", "task",
        "--data-dir", str(tmp_path / "data"), "--prompt-file", str(source),
        "--max-budget-usd", "0.1", "--model", "haiku",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["output"] == "done"
    with Julius(tmp_path / "data") as julius:
        events = julius.ledger.events()
    assert len(events) == 1
    event = events[0]
    assert event["payload"]["observationScope"] == "session_delta"
    assert event["payload"]["inputTokens"] == 60
    assert event["payload"]["cacheReadTokens"] == 20
    assert event["payload"]["cacheWriteTokens"] == 30
    assert event["payload"]["costProvenance"]["estimateSource"] == "client_result"
    assert event["taskId"] == "task"
    assert "private synthetic prompt" not in json.dumps(events)
