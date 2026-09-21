import json
import subprocess
from pathlib import Path

import pytest

from julius.claude_print_runner import parse_stream_json, run_claude_print


def stream(*events):
    return "\n".join(json.dumps(event) for event in events) + "\n"


def test_parser_uses_final_session_totals_without_nested_double_count():
    parsed = parse_stream_json(stream(
        {"type": "assistant", "message": {"model": "claude-one", "usage": {
            "input_tokens": 99, "output_tokens": 99,
        }}},
        {"type": "result", "subtype": "success", "is_error": False,
         "session_id": "session", "usage": {"input_tokens": 12, "output_tokens": 4,
         "cache_read_input_tokens": 3, "cache_creation_input_tokens": 2},
         "total_cost_usd": 0.02, "result": "synthetic answer"},
    ), exit_code=0)
    assert parsed["complete"] is True
    assert parsed["usage"]["input_tokens"] == 12
    assert parsed["usage"]["output_tokens"] == 4
    assert parsed["actual_model"] == "claude-one"
    assert parsed["scope"] == "claude_session_delta"
    assert parsed["output"] == "synthetic answer"


def test_multi_model_unknown_and_incomplete_usage_stays_unknown():
    parsed = parse_stream_json(stream(
        {"type": "assistant", "message": {"model": "one"}},
        {"type": "result", "subtype": "error_max_turns", "is_error": True,
         "modelUsage": {"one": {}, "two": {}},
         "usage": {"input_tokens": True, "output_tokens": -1},
         "total_cost_usd": -1},
    ), exit_code=1)
    assert parsed["complete"] is False
    assert parsed["actual_model"] is None
    assert parsed["observed_models"] == ["one", "two"]
    assert parsed["usage"]["input_tokens"] is None
    assert parsed["usage"]["output_tokens"] is None
    assert parsed["cost_usd"] is None


def test_runner_uses_stdin_ephemeral_config_and_bounded_flags(tmp_path):
    observed = {}

    def fake_run(argv, **kwargs):
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        observed["settings"] = json.loads(Path(argv[2]).read_text())
        observed["mcp"] = json.loads(Path(argv[4]).read_text())
        return subprocess.CompletedProcess(argv, 0, stream(
            {"type": "result", "subtype": "success", "is_error": False,
             "usage": {"input_tokens": 1, "output_tokens": 2}},
        ), "")

    result = run_claude_print(
        prompt="synthetic prompt", project_id="p", data_dir=tmp_path,
        max_turns=2, max_budget_usd=0.1, timeout_seconds=3, model="haiku", runner=fake_run,
    )
    assert result["complete"] is True
    assert observed["kwargs"]["input"] == "synthetic prompt"
    assert observed["kwargs"]["timeout"] == 3
    assert "synthetic prompt" not in " ".join(observed["argv"])
    assert "--no-session-persistence" in observed["argv"]
    assert "--max-turns" in observed["argv"]
    assert "--max-budget-usd" in observed["argv"]
    assert observed["argv"][observed["argv"].index("--model") + 1] == "haiku"
    assert observed["settings"] == {}
    assert "julius-recovery" in observed["mcp"]["mcpServers"]
    assert not Path(observed["argv"][2]).exists()


def test_timeout_is_incomplete_and_limits_are_required(tmp_path):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    result = run_claude_print(
        prompt="synthetic", project_id="p", data_dir=tmp_path,
        max_turns=1, max_budget_usd=0.1, timeout_seconds=1, runner=timeout,
    )
    assert result["complete"] is False
    assert result["error"] == "missing_result"
    with pytest.raises(ValueError, match="max_turns"):
        run_claude_print(prompt="x", project_id="p", data_dir=tmp_path,
                         max_turns=0, max_budget_usd=1.0, timeout_seconds=1)
