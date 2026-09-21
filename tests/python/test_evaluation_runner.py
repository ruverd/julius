import pytest
from pydantic import ValidationError

from julius.evaluation_runner import Attempt, FrozenFixture, replay_paired_fixtures


def fixture(task_id="task", snapshot=None):
    snapshot = {"prompt": "frozen"} if snapshot is None else snapshot
    return FrozenFixture(
        task_id=task_id, fixture_id=FrozenFixture.digest(task_id, snapshot), snapshot=snapshot,
    )


def attempt(item, arm, index, success, *, input_tokens=10, cost=1.0):
    return Attempt(
        fixture_id=item.fixture_id, arm_id=arm, attempt_index=index, success=success,
        input_tokens=input_tokens, output_tokens=2, cache_read_tokens=0,
        cache_write_tokens=0, auxiliary_tokens=0, cost_usd=cost, latency_ms=5.0,
    )


def test_replay_preserves_failures_retries_and_negative_savings():
    item = fixture()
    result = replay_paired_fixtures([item], [
        attempt(item, "base", 0, False), attempt(item, "base", 1, True),
        attempt(item, "new", 0, False, input_tokens=30, cost=3.0),
    ], baseline_arm="base", candidate_arm="new")
    assert result["scope"] == "offline_fixture_replay"
    assert result["fixture_ids"]["task"] == item.fixture_id
    assert result["analysis"]["baseline"]["attempts"] == 2
    assert result["analysis"]["baseline"]["retries"] == 1
    assert result["analysis"]["candidate"]["failures"] == 1
    assert result["analysis"]["savings"]["input_tokens"] == -10
    assert result["analysis"]["savings"]["cost_usd"] == -1.0
    assert len(result["attempts"]) == 3


def test_unknown_measurement_stays_null():
    item = fixture()
    records = [attempt(item, "base", 0, True), attempt(item, "new", 0, True)]
    records[1] = records[1].model_copy(update={"cost_usd": None})
    result = replay_paired_fixtures([item], records, baseline_arm="base", candidate_arm="new")
    assert result["analysis"]["savings"]["cost_usd"] is None


def test_rejects_snapshot_drift_and_incomplete_attempt_history():
    item = fixture()
    with pytest.raises(ValidationError, match="Fixture ID"):
        FrozenFixture(task_id="task", fixture_id=item.fixture_id, snapshot={"prompt": "changed"})
    with pytest.raises(ValueError, match="contiguous"):
        replay_paired_fixtures([item], [attempt(item, "base", 1, True),
                                        attempt(item, "new", 0, True)],
                               baseline_arm="base", candidate_arm="new")
    with pytest.raises(ValueError, match="after success"):
        replay_paired_fixtures([item], [attempt(item, "base", 0, True),
                                        attempt(item, "base", 1, True),
                                        attempt(item, "new", 0, True)],
                               baseline_arm="base", candidate_arm="new")
