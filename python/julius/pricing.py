"""Offline, caller-supplied modeled USD pricing."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _count(value: Any) -> bool:
    return value is None or type(value) is int and 0 <= value <= 2**53 - 1


def _money(value: Any) -> bool:
    return value is None or type(value) in (int, float) and math.isfinite(value) and value >= 0


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None


def _snapshot(snapshot: dict[str, Any]) -> tuple[datetime, datetime | None]:
    if (
        not all(
            _nonempty(snapshot.get(key))
            for key in ("id", "modelId", "providerId", "source", "tier")
        )
        or snapshot.get("currency") != "USD"
    ):
        raise ValueError("Invalid price snapshot")
    effective = _instant(snapshot.get("effectiveAt"))
    expires = _instant(snapshot.get("expiresAt")) if "expiresAt" in snapshot else None
    if effective is None or ("expiresAt" in snapshot and (expires is None or expires <= effective)):
        raise ValueError("Invalid price snapshot")
    rates = snapshot.get("ratesPerMillion")
    if not isinstance(rates, dict) or any(
        key not in rates or not _money(rates[key])
        for key in ("inputUncached", "cacheRead", "cacheWrite", "output")
    ):
        raise ValueError("Invalid price rate")
    return effective, expires


def price_usage(usage: dict[str, Any], snapshot: dict[str, Any] | None) -> dict[str, Any]:
    call_id = usage.get("callId")
    if not _nonempty(call_id) or any(
        not _count(usage.get(key))
        for key in ("inputTokens", "cacheReadTokens", "cacheWriteTokens", "outputTokens")
    ):
        raise ValueError("Invalid usage for pricing")
    snapshot_id = usage.get("priceSnapshotId")
    if (
        not snapshot
        or not snapshot_id
        or snapshot.get("id") != snapshot_id
        or usage.get("modelId") != snapshot.get("modelId")
        or usage.get("providerId") != snapshot.get("providerId")
    ):
        return {"callId": call_id, "modeledCostUsd": None, "priceSnapshotId": snapshot_id}
    effective, expires = _snapshot(snapshot)
    occurred = _instant(usage.get("occurredAt"))
    if occurred is None or occurred < effective or (expires is not None and occurred >= expires):
        return {"callId": call_id, "modeledCostUsd": None, "priceSnapshotId": snapshot_id}
    input_tokens, read, write, output = (
        usage.get(key)
        for key in ("inputTokens", "cacheReadTokens", "cacheWriteTokens", "outputTokens")
    )
    if input_tokens is None or read is None or write is None or output is None:
        return {"callId": call_id, "modeledCostUsd": None, "priceSnapshotId": snapshot_id}
    uncached = input_tokens - read - write
    if uncached < 0:
        raise ValueError("Cache counters exceed input total")
    rates = snapshot["ratesPerMillion"]
    parts: tuple[tuple[int, float | int | None], ...] = (
        (uncached, rates["inputUncached"]),
        (read, rates["cacheRead"]),
        (write, rates["cacheWrite"]),
        (output, rates["output"]),
    )
    if any(tokens > 0 and rate is None for tokens, rate in parts):
        return {"callId": call_id, "modeledCostUsd": None, "priceSnapshotId": snapshot_id}
    cost = sum(tokens * (rate or 0) / 1_000_000 for tokens, rate in parts)
    if not math.isfinite(cost):
        raise ValueError("Modeled cost overflow")
    return {"callId": call_id, "modeledCostUsd": cost, "priceSnapshotId": snapshot_id}


def compare_modeled_costs(
    baseline: dict[str, Any],
    usage: list[dict[str, Any]],
    overhead: list[dict[str, Any]] | None = None,
    coverage_complete: bool = False,
) -> dict[str, Any]:
    overhead = [] if overhead is None else overhead
    if (
        not _nonempty(baseline.get("id"))
        or not _nonempty(baseline.get("comparisonScope"))
        or baseline.get("evidence") not in ("reconstructed_baseline", "controlled_experiment")
        or not _money(baseline.get("modeledCostUsd"))
    ):
        raise ValueError("Invalid comparable baseline")
    call_ids: set[str] = set()
    for item in usage:
        call_id = item.get("callId")
        if not _nonempty(call_id) or call_id in call_ids or not _money(item.get("modeledCostUsd")):
            raise ValueError("Invalid or duplicate call ID")
        call_ids.add(str(call_id))
    overhead_ids: set[str] = set()
    for item in overhead:
        item_id = item.get("id")
        if (
            not _nonempty(item_id)
            or item_id in overhead_ids
            or item.get("kind") not in ("local", "external")
            or not _money(item.get("costUsd"))
        ):
            raise ValueError("Invalid or duplicate overhead ID")
        overhead_ids.add(str(item_id))
    observed = (
        sum(item["modeledCostUsd"] for item in usage)
        if (usage or coverage_complete)
        and all(item.get("modeledCostUsd") is not None for item in usage)
        else None
    )
    overhead_cost = (
        sum(item["costUsd"] for item in overhead)
        if all(item.get("costUsd") is not None for item in overhead)
        else None
    )
    if any(value is not None and not math.isfinite(value) for value in (observed, overhead_cost)):
        raise ValueError("Modeled cost overflow")
    base_cost = baseline.get("modeledCostUsd")
    net = (
        base_cost - observed - overhead_cost
        if base_cost is not None and observed is not None and overhead_cost is not None
        else None
    )
    if net is not None and not math.isfinite(net):
        raise ValueError("Modeled cost overflow")
    return {
        "baselineId": baseline["id"],
        "baselineEvidence": baseline["evidence"],
        "baselineModeledCostUsd": base_cost,
        "observedModeledCostUsd": observed,
        "overheadUsd": overhead_cost,
        "netModeledSavingsUsd": net,
    }
