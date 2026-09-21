import pytest
from pydantic import ValidationError

from julius.evaluation import Trial, analyze_paired_trials


def trial(arm: str, task: str, *, success: bool = True, cost: float | None = 1.0,
          retries: int = 0, input_tokens: int | None = 100) -> Trial:
    return Trial(arm_id=arm, task_id=task, success=success, cost_usd=cost,
                 retries=retries, input_tokens=input_tokens, output_tokens=10,
                 cache_read_tokens=0, cache_write_tokens=0, auxiliary_tokens=0,
                 latency_ms=100.0)


def test_paired_failures_retry_denominators_and_negative_savings() -> None:
    result = analyze_paired_trials([
        trial("base", "a", success=False, cost=1.0, retries=1),
        trial("new", "a", success=True, cost=2.0, retries=2),
        trial("base", "b", success=True, cost=1.0),
        trial("new", "b", success=False, cost=1.0),
        trial("base", "unmatched", cost=50.0),
    ], baseline_arm="base", candidate_arm="new")
    assert result["paired_task_ids"] == ["a", "b"]
    assert result["unpaired_baseline_task_ids"] == ["unmatched"]
    assert result["baseline"]["attempts"] == 3
    assert result["candidate"]["attempts"] == 4
    assert result["candidate"]["failures"] == 1
    assert result["candidate"]["per_attempt"]["cost_usd"] == 0.75
    assert result["candidate"]["attempted_tasks"] == 2
    assert result["candidate"]["resolved_tasks"] == 1
    assert result["candidate"]["per_attempted_task"]["cost_usd"] == 1.5
    assert result["candidate"]["per_resolved_task"]["cost_usd"] == 3.0
    assert result["savings"]["cost_usd"] == -1.0
    assert result["paired_tasks"][0]["savings"]["cost_usd"] == -1.0


def test_unknown_propagates_and_empty_pairing_has_null_rates() -> None:
    result = analyze_paired_trials([trial("base", "x", input_tokens=None),
                                    trial("new", "x", cost=None)],
                                   baseline_arm="base", candidate_arm="new")
    assert result["savings"]["input_tokens"] is None
    assert result["savings"]["cost_usd"] is None
    empty = analyze_paired_trials([], baseline_arm="base", candidate_arm="new")
    assert empty["baseline"]["success_rate"] is None
    assert empty["baseline"]["totals"]["cost_usd"] is None
    assert empty["baseline"]["per_attempt"]["cost_usd"] is None


def test_rejects_duplicate_pairs_and_invalid_counters() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        analyze_paired_trials([trial("base", "a"), trial("base", "a")],
                              baseline_arm="base", candidate_arm="new")
    with pytest.raises(ValidationError):
        trial("base", "a", retries=True)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Trial(arm_id="base", task_id="a", success=True, cost_usd=float("nan"))


def test_failed_runs_have_no_resolved_task_denominator() -> None:
    result = analyze_paired_trials([trial("base", "x", success=False),
                                    trial("new", "x", success=False)],
                                   baseline_arm="base", candidate_arm="new")
    assert result["candidate"]["attempted_tasks"] == 1
    assert result["candidate"]["resolved_tasks"] == 0
    assert result["candidate"]["per_attempted_task"]["cost_usd"] == 1.0
    assert result["candidate"]["per_resolved_task"]["cost_usd"] is None


def test_cache_tokens_cannot_exceed_input() -> None:
    with pytest.raises(ValidationError, match="Cache tokens"):
        Trial(arm_id="base", task_id="x", success=True, input_tokens=3,
              cache_read_tokens=2, cache_write_tokens=2)
    Trial(arm_id="base", task_id="x", success=True, input_tokens=None,
          cache_read_tokens=2, cache_write_tokens=2)
