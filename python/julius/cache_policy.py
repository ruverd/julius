"""Offline cache-aware comparison of complete candidate requests."""

from __future__ import annotations

import math
from typing import Any

from julius.pricing import price_usage


def decide_cache_aware(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    snapshot: dict[str, Any] | None,
    *,
    optimizer_overhead_usd: float | None,
    risk_margin_usd: float | None,
) -> dict[str, Any]:
    """Compare two full requests using one dated, caller-selected price snapshot.

    Each request supplies the same ``modelId``, ``providerId``, ``tokenizerId``
    and ``occurredAt``. Cache counters must be marked observed or estimated.
    Unknown money or counters yields an unknown decision, never a zero estimate.
    """
    for request in (baseline, candidate):
        if not isinstance(request, dict):
            raise ValueError("Invalid request")
        if request.get("cacheEvidence") not in ("observed", "estimated"):
            raise ValueError("Cache evidence must be observed or estimated")
        if request.get("counterEvidence") not in (
            "provider_reported", "tokenizer_counted", "estimated"
        ):
            raise ValueError("Counter evidence must identify its source")
        if not isinstance(request.get("tokenizerId"), str) or not request["tokenizerId"].strip():
            raise ValueError("A tokenizer ID is required")
    for key in ("modelId", "providerId", "tokenizerId", "occurredAt"):
        if baseline.get(key) != candidate.get(key):
            raise ValueError(f"Candidates differ in {key}")
    if baseline.get("callId") == candidate.get("callId"):
        raise ValueError("Candidates require distinct call IDs")
    for name, value in (("optimizer overhead", optimizer_overhead_usd), ("risk margin", risk_margin_usd)):
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise ValueError(f"Invalid {name}")
    baseline_cost = price_usage(baseline, snapshot)["modeledCostUsd"]
    candidate_cost = price_usage(candidate, snapshot)["modeledCostUsd"]
    benefit = (
        baseline_cost - candidate_cost - optimizer_overhead_usd
        if baseline_cost is not None
        and candidate_cost is not None
        and optimizer_overhead_usd is not None
        else None
    )
    if benefit is not None and not math.isfinite(benefit):
        raise ValueError("Modeled benefit overflow")
    return {
        "baselineModeledCostUsd": baseline_cost,
        "candidateModeledCostUsd": candidate_cost,
        "optimizerOverheadUsd": optimizer_overhead_usd,
        "riskMarginUsd": risk_margin_usd,
        "expectedBenefitUsd": benefit,
        "compress": benefit > risk_margin_usd if benefit is not None and risk_margin_usd is not None else None,
        "priceSnapshotId": baseline.get("priceSnapshotId"),
        "baselineCacheEvidence": baseline["cacheEvidence"],
        "candidateCacheEvidence": candidate["cacheEvidence"],
        "baselineCounterEvidence": baseline["counterEvidence"],
        "candidateCounterEvidence": candidate["counterEvidence"],
        "decisionEvidence": "expected",
    }
