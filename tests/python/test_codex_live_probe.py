"""Synthetic Codex CLI JSONL fixtures; tests never invoke a model."""

import json
import subprocess
from pathlib import Path

import pytest

from julius.codex_live_probe import parse_codex_jsonl, probe_codex_usage


def stream(usage):
    return "\n".join(json.dumps(item) for item in (
        {"type": "thread.started", "thread_id": "session-1"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "private prompt text"}},
        {"type": "turn.completed", "usage": usage},
    )).encode()


def test_parse_documented_usage_without_content():
    result = parse_codex_jsonl(stream({
        "input_tokens": 100, "cached_input_tokens": 40,
        "output_tokens": 5, "reasoning_output_tokens": 2,
    }))
    assert result["inputTokens"] == 100
    assert result["cachedInputTokens"] == 40
    assert result["outputTokens"] == 5
    assert result["reasoningOutputTokens"] == 2
    assert "private prompt text" not in str(result)


def test_unknown_and_invalid_counters_remain_null():
    result = parse_codex_jsonl(stream({"input_tokens": True, "output_tokens": -1}))
    assert result["inputTokens"] is None
    assert result["cachedInputTokens"] is None
    assert result["outputTokens"] is None
    assert result["reasoningOutputTokens"] is None


def test_probe_requires_opt_in_and_runs_one_bounded_read_only_command():
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        assert Path(kwargs["cwd"]).is_dir()
        return subprocess.CompletedProcess(command, 0, stdout=stream({"input_tokens": 10}))

    with pytest.raises(ValueError, match="explicit confirmation"):
        probe_codex_usage(runner=fake_run)
    assert not seen
    result = probe_codex_usage(confirmed=True, runner=fake_run)
    assert result["status"] == "complete"
    assert result["usage"]["inputTokens"] == 10
    assert result["usage"]["outputTokens"] is None
    assert seen["command"][:6] == ["codex", "exec", "--json", "--ephemeral", "--sandbox", "read-only"]
    assert "--ignore-user-config" in seen["command"]
    assert "--ignore-rules" in seen["command"]
    assert seen["kwargs"]["timeout"] == 30
    assert not Path(seen["kwargs"]["cwd"]).exists()


def test_probe_timeout_and_malformed_output_are_not_zero_usage():
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 30)

    assert probe_codex_usage(confirmed=True, runner=timeout) == {"status": "timeout", "usage": None}
    def malformed(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=b"not-json")
    assert probe_codex_usage(confirmed=True, runner=malformed) == {"status": "invalid_output", "usage": None}


def test_rejects_multiple_completed_turns():
    raw = b'{"type":"turn.completed","usage":{}}\n{"type":"turn.completed","usage":{}}\n'
    with pytest.raises(ValueError, match="multiple"):
        parse_codex_jsonl(raw)
