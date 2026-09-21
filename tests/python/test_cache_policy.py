import pytest

from julius.cache_policy import decide_cache_aware


SNAPSHOT = {
    "id": "dated", "modelId": "m", "providerId": "p", "source": "caller",
    "effectiveAt": "2026-09-21T00:00:00Z", "currency": "USD", "tier": "standard",
    "ratesPerMillion": {"inputUncached": 10, "cacheRead": 1, "cacheWrite": 12, "output": 20},
}
BASE = {
    "callId": "base", "modelId": "m", "providerId": "p", "tokenizerId": "tok",
    "occurredAt": "2026-09-21T12:00:00Z", "priceSnapshotId": "dated",
    "inputTokens": 1000, "cacheReadTokens": 900, "cacheWriteTokens": 0,
    "outputTokens": 100, "cacheEvidence": "observed", "counterEvidence": "provider_reported",
}
CANDIDATE = {
    **BASE, "callId": "compressed", "inputTokens": 500, "cacheReadTokens": 0,
    "cacheEvidence": "estimated", "counterEvidence": "estimated",
}


def compare(baseline=BASE, candidate=CANDIDATE, snapshot=SNAPSHOT, overhead=0.0, margin=0.0):
    return decide_cache_aware(
        baseline, candidate, snapshot,
        optimizer_overhead_usd=overhead, risk_margin_usd=margin,
    )


def test_warm_cache_rejects_shorter_request_and_keeps_negative_benefit():
    result = compare()
    assert result["baselineModeledCostUsd"] == pytest.approx(0.0039)
    assert result["candidateModeledCostUsd"] == pytest.approx(0.007)
    assert result["expectedBenefitUsd"] == pytest.approx(-0.0031)
    assert result["compress"] is False
    assert result["baselineCacheEvidence"] == "observed"
    assert result["candidateCacheEvidence"] == "estimated"
    assert result["baselineCounterEvidence"] == "provider_reported"
    assert result["candidateCounterEvidence"] == "estimated"
    assert result["decisionEvidence"] == "expected"


def test_positive_benefit_must_exceed_overhead_and_risk():
    cold = {**BASE, "cacheReadTokens": 0, "cacheEvidence": "estimated"}
    assert compare(cold, overhead=0.001, margin=0.001)["compress"] is True
    assert compare(cold, overhead=0.005, margin=0.001)["compress"] is False


def test_unknown_prices_counts_and_overhead_remain_unknown():
    assert compare(snapshot=None)["compress"] is None
    assert compare(candidate={**CANDIDATE, "cacheReadTokens": None})["compress"] is None
    assert compare(overhead=None)["expectedBenefitUsd"] is None
    assert compare(margin=None)["compress"] is None


def test_requires_comparable_full_requests_and_valid_counters():
    with pytest.raises(ValueError, match="tokenizerId"):
        compare(candidate={**CANDIDATE, "tokenizerId": "other"})
    with pytest.raises(ValueError, match="Cache evidence"):
        compare(candidate={**CANDIDATE, "cacheEvidence": None})
    with pytest.raises(ValueError, match="Counter evidence"):
        compare(candidate={**CANDIDATE, "counterEvidence": None})
    with pytest.raises(ValueError, match="Cache counters"):
        compare(candidate={**CANDIDATE, "cacheReadTokens": 600})
    with pytest.raises(ValueError, match="Invalid risk margin"):
        compare(margin=-1)
