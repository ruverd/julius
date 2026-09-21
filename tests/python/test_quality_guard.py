import pytest
from pydantic import ValidationError

from julius.quality_guard import (
    GuardPolicy, ManualAction, Scope, TaskOutcome, decide_suspension,
)


SCOPE = Scope(project_id="p", model_id="m", strategy_id="s", strategy_version="v1")
POLICY = GuardPolicy(
    version="1", minimum_samples=2, max_error_rate=0.25,
    max_recovery_rate=0.5, max_rework_rate=0.5,
    max_mean_latency_ms=100.0, min_total_net_savings_usd=0.0,
)


def outcome(sequence, task, **changes):
    data = dict(scope=SCOPE, sequence=sequence, task_id=task, error=False,
                recovery_used=False, rework_needed=False, latency_ms=10.0,
                net_savings_usd=1.0)
    data.update(changes)
    return TaskOutcome(**data)


def test_known_bad_metrics_suspend_and_preserve_negative_economics():
    result = decide_suspension(SCOPE, POLICY, [
        outcome(1, "a", error=True, net_savings_usd=-3.0),
        outcome(2, "b", net_savings_usd=1.0),
    ])
    assert result["status"] == "suspended"
    assert result["reasons"] == ["above_max_error_rate", "below_min_total_net_savings_usd"]
    assert result["metrics"]["total_net_savings_usd"]["value"] == -2.0


def test_unknown_values_never_count_as_zero_or_clear_suspension():
    result = decide_suspension(SCOPE, POLICY, [
        outcome(1, "a", error=None, latency_ms=None), outcome(2, "b"),
    ])
    assert result["status"] == "insufficient_evidence"
    assert result["metrics"]["error_rate"] == {"known_samples": 1, "value": None}
    assert result["metrics"]["mean_latency_ms"]["value"] is None


def test_manual_disable_and_reenable_start_new_evidence_window():
    records = [outcome(1, "a", error=True), outcome(2, "b")]
    disable = ManualAction(scope=SCOPE, sequence=3, action="disable", reason="operator")
    assert decide_suspension(SCOPE, POLICY, records, [disable])["status"] == "manual_disabled"
    enable = ManualAction(scope=SCOPE, sequence=4, action="reenable", reason="reviewed")
    assert decide_suspension(SCOPE, POLICY, records, [disable, enable])["status"] == "insufficient_evidence"
    assert decide_suspension(SCOPE, POLICY, records + [outcome(5, "c"), outcome(6, "d")],
                             [disable, enable])["status"] == "enabled"


def test_rejects_cross_scope_duplicates_and_invalid_counts():
    with pytest.raises(ValueError, match="Sequences"):
        decide_suspension(SCOPE, POLICY, [outcome(1, "a"), outcome(1, "b")])
    with pytest.raises(ValueError, match="unique task"):
        decide_suspension(SCOPE, POLICY, [outcome(1, "a"), outcome(2, "a")])
    with pytest.raises(ValidationError):
        outcome(1, "a", latency_ms=-1.0)
