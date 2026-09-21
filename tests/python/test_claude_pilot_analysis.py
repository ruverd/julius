import copy
import json
import subprocess

import pytest

from julius.claude_pair import PILOT_TASKS
from julius.claude_pilot import run_claude_pilot
from julius.claude_pilot_analysis import analyze_claude_pilot_report


def _report(tmp_path):
    def fake_run(argv, **kwargs):
        task = next(task for task in PILOT_TASKS if task["prompt"] == kwargs["input"])
        events = [
            {"type": "assistant", "message": {"model": "fixture", "content": [
                {"type": "tool_use", "id": "one", "name": "Bash", "input": {"command": task["command"]}},
            ]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "one", "content": "fixture"},
            ]}},
            {"type": "result", "subtype": "success", "is_error": False,
             "result": task["answer"], "session_id": "fixture",
             "usage": {"input_tokens": 10, "output_tokens": 2,
                       "cache_read_input_tokens": 4, "cache_creation_input_tokens": 3},
             "total_cost_usd": 0.02},
        ]
        return subprocess.CompletedProcess(argv, 0, "\n".join(map(json.dumps, events)) + "\n", "")

    return run_claude_pilot(work_dir=tmp_path, project_id="fixture", max_turns=1,
                            max_budget_usd=0.1, timeout_seconds=1,
                            order_seed=4, runner=fake_run)


def test_analysis_normalizes_usage_and_retains_failures(tmp_path):
    report = _report(tmp_path)
    report["attempts"][0]["passed"] = False
    report["attempts"][0]["answer"] = "wrong"
    report["attempts"][0]["usage"]["input_tokens"] = None
    result = analyze_claude_pilot_report(report, resamples=100)
    assert len(result["trials"]) == 12
    assert result["trials"][0]["success"] is False
    assert result["trials"][0]["input_tokens"] is None
    assert result["trials"][1]["input_tokens"] == 17
    assert result["trials"][1]["cache_read_tokens"] == 4
    assert result["paired_analysis"]["baseline"]["attempted_tasks"] == 6
    assert result["paired_analysis"]["candidate"]["attempted_tasks"] == 6
    assert result["paired_analysis"]["savings"]["input_tokens"] is None
    assert result["paired_analysis"]["bootstrap"]["intervals"]["input_tokens"]["lower"] is None
    assert "not_direct_savings" in result["interpretation"]
    assert result["model_comparability"] == "same_observed_model"


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(corpus_sha256="0" * 64),
    lambda r: r["tasks"][0].update(task_sha256="0" * 64),
    lambda r: r["attempts"][0].update(task_sha256="0" * 64),
    lambda r: r["order"][0].update(execution_sequence=2),
    lambda r: r["attempts"][0].update(execution_sequence=2),
    lambda r: r["attempts"].pop(),
    lambda r: r["attempts"][0].update(arm=r["attempts"][1]["arm"]),
    lambda r: r.update(complete=False),
    lambda r: r.update(order_seed=r["order_seed"] + 1),
    lambda r: r["attempts"][0].update(passed=False),
    lambda r: r["attempts"][0].update(client_version="other"),
    lambda r: r["attempts"][0].update(cache_state="other"),
])
def test_analysis_rejects_incomplete_or_tampered_report(tmp_path, mutation):
    report = copy.deepcopy(_report(tmp_path))
    mutation(report)
    with pytest.raises(ValueError):
        analyze_claude_pilot_report(report, resamples=100)


def test_analysis_flags_mixed_or_unknown_models(tmp_path):
    report = _report(tmp_path)
    report["attempts"][0]["actual_model"] = None
    report["attempts"][0]["observed_models"] = []
    result = analyze_claude_pilot_report(report, resamples=100)
    assert result["model_comparability"] == "mixed_or_unknown"
