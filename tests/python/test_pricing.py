import pytest

from julius.pricing import compare_modeled_costs, price_usage


SNAPSHOT = {
    "id": "price",
    "modelId": "m",
    "providerId": "p",
    "source": "user",
    "effectiveAt": "2026-09-21T00:00:00Z",
    "currency": "USD",
    "tier": "standard",
    "ratesPerMillion": {"inputUncached": 1, "cacheRead": 0.1, "cacheWrite": 2, "output": 4},
}
USAGE = {
    "callId": "a",
    "modelId": "m",
    "providerId": "p",
    "inputTokens": 1000,
    "cacheReadTokens": 500,
    "cacheWriteTokens": 100,
    "outputTokens": 200,
    "priceSnapshotId": "price",
    "occurredAt": "2026-09-21T12:00:00Z",
}
BASELINE = {
    "id": "baseline",
    "evidence": "controlled_experiment",
    "comparisonScope": "same-task",
    "modeledCostUsd": 0.001,
}


def test_price_requires_exact_snapshot_and_all_rates():
    assert price_usage(USAGE, SNAPSHOT)["modeledCostUsd"] == pytest.approx(0.00145)
    assert price_usage({**USAGE, "modelId": None}, SNAPSHOT)["modeledCostUsd"] is None
    with pytest.raises(ValueError, match="Invalid price rate"):
        price_usage(USAGE, {**SNAPSHOT, "ratesPerMillion": {"output": 4}})
    with pytest.raises(ValueError, match="Invalid usage"):
        price_usage({**USAGE, "inputTokens": True}, SNAPSHOT)


def test_signed_net_unknown_coverage_and_duplicates():
    assert (
        compare_modeled_costs(BASELINE, [price_usage(USAGE, SNAPSHOT)])["netModeledSavingsUsd"] < 0
    )
    assert compare_modeled_costs(BASELINE, [])["netModeledSavingsUsd"] is None
    assert (
        compare_modeled_costs(BASELINE, [], coverage_complete=True)["netModeledSavingsUsd"] == 0.001
    )
    with pytest.raises(ValueError, match="duplicate call ID"):
        item = price_usage(USAGE, SNAPSHOT)
        compare_modeled_costs(BASELINE, [item, item])


def test_temporal_snapshot_attribution_is_explicit():
    assert price_usage({**USAGE, "occurredAt": "2026-09-20T23:59:59Z"}, SNAPSHOT)["modeledCostUsd"] is None
    assert price_usage({key: value for key, value in USAGE.items() if key != "occurredAt"}, SNAPSHOT)["modeledCostUsd"] is None
    assert price_usage({**USAGE, "occurredAt": "2026-09-21T12:00:00"}, SNAPSHOT)["modeledCostUsd"] is None
    expiring = {**SNAPSHOT, "expiresAt": "2026-09-21T12:00:00Z"}
    assert price_usage(USAGE, expiring)["modeledCostUsd"] is None
    assert price_usage({**USAGE, "occurredAt": "2026-09-21T11:59:59Z"}, expiring)["modeledCostUsd"] is not None
    assert price_usage({**USAGE, "occurredAt": "2030-01-01T00:00:00Z"}, SNAPSHOT)["modeledCostUsd"] is not None
    with pytest.raises(ValueError, match="Invalid price snapshot"):
        price_usage(USAGE, {**SNAPSHOT, "effectiveAt": "2026-09-21T00:00:00"})
