"""The Codex CLI command is tested without invoking a model."""

import json

import pytest

import julius.cli as cli
from julius.sdk import Julius


def test_probe_records_one_runtime_reported_session_delta(tmp_path, monkeypatch, capsys):
    calls = []

    def fake_probe(*, confirmed):
        calls.append(confirmed)
        return {
            "status": "complete",
            "usage": {
                "threadId": "thread-1",
                "turnCompleted": True,
                "failed": False,
                "inputTokens": 100,
                "cachedInputTokens": 40,
                "outputTokens": 5,
                "reasoningOutputTokens": 2,
                "evidence": "codex_cli_jsonl",
            },
        }

    monkeypatch.setattr(cli, "probe_codex_usage", fake_probe)
    data_dir = tmp_path / "data"
    assert cli.run([
        "probe", "codex", "--project", "project", "--task", "task",
        "--data-dir", str(data_dir),
    ]) == 0
    assert calls == [True]
    printed = json.loads(capsys.readouterr().out)
    assert printed["result"]["status"] == "complete"
    with Julius(data_dir) as julius:
        events = julius.ledger.events()
    assert len(events) == 1
    event = events[0]
    assert event["projectId"] == "project"
    assert event["taskId"] == "task"
    assert event["sessionId"] == "thread-1"
    assert event["clientId"] == "codex-cli"
    assert event["evidence"] == "runtime_reported"
    assert event["modelId"] is None
    assert event["providerId"] is None
    assert event["payload"]["observationScope"] == "session_delta"
    assert event["payload"]["inputTokens"] == 100
    assert event["payload"]["cacheReadTokens"] == 40
    assert event["payload"]["outputTokens"] == 5
    assert event["payload"]["costUsd"] is None
    assert event["payload"]["complete"] is True


@pytest.mark.parametrize("result", [
    {"status": "timeout", "usage": None},
    {"status": "incomplete", "usage": {
        "threadId": None, "turnCompleted": False, "failed": True,
        "inputTokens": None, "cachedInputTokens": None,
        "outputTokens": None, "reasoningOutputTokens": None,
    }},
    {"status": "complete", "usage": {
        "threadId": "thread-2", "turnCompleted": True, "failed": False,
        "inputTokens": 10, "cachedInputTokens": None,
        "outputTokens": None, "reasoningOutputTokens": None,
    }},
])
def test_probe_incomplete_usage_stays_unknown(tmp_path, monkeypatch, capsys, result):
    monkeypatch.setattr(cli, "probe_codex_usage", lambda *, confirmed: result)
    data_dir = tmp_path / "data"
    assert cli.run(["probe", "codex", "--project", "project", "--data-dir", str(data_dir)]) == 2
    capsys.readouterr()
    with Julius(data_dir) as julius:
        events = julius.ledger.events()
    assert len(events) == 1
    event = events[0]
    assert event["payload"]["complete"] is False
    assert event["payload"]["costUsd"] is None
    assert event["payload"]["cacheWriteTokens"] is None
    assert event["payload"]["outputTokens"] is None


def test_probe_requires_project_and_exact_subcommand_before_running(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "probe_codex_usage", lambda **kwargs: calls.append(kwargs))
    with pytest.raises(ValueError, match="Missing --project"):
        cli.run(["probe", "codex", "--data-dir", str(tmp_path)])
    with pytest.raises(ValueError, match="Use probe codex"):
        cli.run(["probe", "other", "--project", "project", "--data-dir", str(tmp_path)])
    assert calls == []
