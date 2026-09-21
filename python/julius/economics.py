"""Offline task economics with explicit counterfactual and measurement limits."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any

from julius.pricing import price_usage


def _sum_known(values: Sequence[int | float | None], *, complete: bool) -> int | float | None:
    return sum(value for value in values if value is not None) if complete and all(value is not None for value in values) else None


def _cost(call: dict[str, Any], prices: Mapping[str, dict[str, Any]]) -> float | None:
    snapshot_id = call.get("priceSnapshotId")
    return price_usage(call, prices.get(snapshot_id) if isinstance(snapshot_id, str) else None)[
        "modeledCostUsd"
    ]


def analyze_task(
    events: Sequence[dict[str, Any]],
    baseline: dict[str, Any] | None = None,
    prices: Mapping[str, dict[str, Any]] | None = None,
    overhead: Sequence[dict[str, Any]] = (),
    *,
    coverage_complete: bool = False,
) -> dict[str, Any]:
    """Analyze one task. `coverage_complete` is caller attestation, never inferred.

    Baseline must supply real comparable calls, each priced using its own model snapshot.
    Output baseline remains unknown unless supplied by controlled experiment or
    reconstructed baseline. Only observed calls count toward current cost.
    """
    prices = prices or {}
    task_ids = {event.get("taskId") for event in events}
    if len(task_ids) != 1 or None in task_ids:
        raise ValueError("Exactly one identified task required")
    task_id = next(iter(task_ids))
    if baseline is not None and (
        baseline.get("taskId") != task_id
        or baseline.get("evidence") not in ("reconstructed_baseline", "controlled_experiment")
        or not isinstance(baseline.get("id"), str)
        or not baseline["id"]
        or not isinstance(baseline.get("calls"), list)
        or ("outputComparable" in baseline and type(baseline["outputComparable"]) is not bool)
    ):
        raise ValueError("Invalid comparable task baseline")
    usage = [e for e in events if e.get("eventType") == "usage"]
    seen_calls: set[str] = set()
    calls: list[dict[str, Any]] = []
    for event in usage:
        payload = event["payload"]
        call_id = payload.get("callId")
        if call_id is not None and (not isinstance(call_id, str) or not call_id):
            raise ValueError("Invalid call ID")
        if call_id is not None:
            if call_id in seen_calls:
                raise ValueError("Duplicate call ID")
            seen_calls.add(call_id)
        calls.append({
            "callId": call_id,
            "modelId": event.get("modelId"),
            "providerId": event.get("providerId"),
            "occurredAt": event["occurredAt"],
            "priceSnapshotId": payload.get("priceSnapshotId"),
            "inputTokens": payload.get("inputTokens"),
            "cacheReadTokens": payload.get("cacheReadTokens"),
            "cacheWriteTokens": payload.get("cacheWriteTokens"),
            "outputTokens": payload.get("outputTokens"),
            "executionLocation": event.get("executionLocation", "unknown"),
            "category": payload.get("category"),
            "complete": payload.get("complete") is True,
            "evidence": event.get("evidence"),
            "eventId": event.get("eventId"),
            "reportedCostUsd": payload.get("costUsd"),
            "costProvenance": payload.get("costProvenance"),
        })
    complete = coverage_complete and all(call["complete"] and call["callId"] is not None for call in calls)
    priced: list[dict[str, Any]] = []
    for call in calls:
        # Provider-reported cost, when present with provenance, takes priority.
        provider_charge = (
            call["reportedCostUsd"] is not None
            and isinstance(call["costProvenance"], dict)
            and call["costProvenance"].get("chargeSource") == "provider_usage"
        )
        client_estimate = (
            call["reportedCostUsd"] is not None
            and isinstance(call["costProvenance"], dict)
            and call["costProvenance"].get("estimateSource") == "client_result"
        )
        cost = (
            call["reportedCostUsd"] if call["costProvenance"] else _cost(call, prices)
        ) if call["callId"] is not None else None
        priced.append({
            **call,
            "costUsd": cost,
            "modeledCostUsd": cost if cost is not None and not provider_charge else None,
            "providerChargedUsd": cost if provider_charge else None,
            "costBasis": "provider_charge" if provider_charge else "client_estimate" if client_estimate else "modeled_price" if cost is not None else None,
        })
    baseline_calls = baseline["calls"] if baseline else []
    baseline_ids = [call.get("callId") for call in baseline_calls]
    if baseline and (any(not isinstance(x, str) or not x for x in baseline_ids) or len(set(baseline_ids)) != len(baseline_ids)):
        raise ValueError("Baseline requires unique call IDs")
    baseline_costs = [_cost(call, prices) for call in baseline_calls]
    current_costs = [call["costUsd"] for call in priced]
    if any(not isinstance(item, dict) for item in overhead):
        raise ValueError("Invalid overhead")
    overhead_ids = [item.get("id") for item in overhead]
    if any(
        not isinstance(item.get("id"), str)
        or not item["id"]
        or item["id"] in seen_calls
        or (item.get("sourceCallId") is not None and (
            not isinstance(item["sourceCallId"], str)
            or item["sourceCallId"] in seen_calls
        ))
        or item.get("kind") not in ("local", "external")
        or item.get("costUsd") is None
        or isinstance(item["costUsd"], bool)
        or not isinstance(item["costUsd"], (int, float))
        or not math.isfinite(item["costUsd"])
        or item["costUsd"] < 0
        for item in overhead
    ) or len(set(overhead_ids)) != len(overhead_ids):
        raise ValueError("Invalid overhead")
    overhead_total = sum(item["costUsd"] for item in overhead)
    current_total = _sum_known(current_costs, complete=complete and bool(calls))
    baseline_total = _sum_known(baseline_costs, complete=bool(baseline_calls))
    net = (
        baseline_total - current_total - overhead_total
        if baseline_total is not None and current_total is not None
        else None
    )
    transforms = [e for e in events if e.get("eventType") == "transform" and e["payload"].get("sent")]
    by_id = {e["payload"]["transformId"]: e for e in transforms}
    direct: list[dict[str, Any]] = []
    for event in transforms:
        payload = event["payload"]
        parent_id = payload.get("parentTransformId")
        parent = by_id.get(parent_id)
        before, after = payload.get("inputTokens"), payload.get("outputTokens")
        comparable = (
            before is not None and after is not None and payload.get("tokenizer") is not None
            and (parent_id is None or (parent is not None and
                parent["payload"].get("outputTokens") == before
                and parent["payload"].get("tokenizer") == payload["tokenizer"]
                and parent.get("modelId") == event.get("modelId")
                and parent["payload"].get("outputArtifactId") == payload.get("inputArtifactId")
            ))
        )
        direct.append({
            "transformId": payload["transformId"],
            "parentTransformId": parent_id,
            "scope": payload["scope"],
            "modelId": event.get("modelId"),
            "tokenizer": payload.get("tokenizer"),
            "evidence": event.get("evidence"),
            "marginalInputReductionTokens": before - after if comparable else None,
        })
    request_reductions = [d["marginalInputReductionTokens"] for d in direct if d["scope"] == "request"]
    observed_output = _sum_known(
        [c["outputTokens"] for c in priced], complete=complete and bool(calls)
    )
    baseline_output = _sum_known(
        [c.get("outputTokens") for c in baseline_calls], complete=bool(baseline_calls)
    )
    comparative_output = (
        baseline_output - observed_output
        if baseline is not None and baseline.get("outputComparable") is True
        and baseline_output is not None and observed_output is not None
        else None
    )
    return {
        "taskId": task_id,
        "coverageComplete": complete,
        "usageRecordsWithoutCallId": sum(call["callId"] is None for call in calls),
        "calls": priced,
        "observedInputTokens": _sum_known([c["inputTokens"] for c in priced], complete=complete and bool(calls)),
        "observedOutputTokens": observed_output,
        "observedLocalTokens": _sum_known([c["inputTokens"] for c in priced if c["executionLocation"] == "local"], complete=complete),
        "observedRemoteTokens": _sum_known([c["inputTokens"] for c in priced if c["executionLocation"] == "remote"], complete=complete),
        "directInputReductionTokens": _sum_known(request_reductions, complete=bool(request_reductions)),
        "transforms": direct,
        "baselineId": baseline["id"] if baseline else None,
        "baselineEvidence": baseline["evidence"] if baseline else None,
        "baselineOutputTokens": baseline_output,
        "outputSavingsTokens": comparative_output,
        "outputSavingsEvidence": baseline["evidence"] if comparative_output is not None and baseline is not None else None,
        "outputSavingsScope": "task_comparison" if comparative_output is not None else None,
        "baselineModeledCostUsd": baseline_total,
        "currentCostUsd": current_total,
        "currentModeledCostUsd": current_total if all(c["costBasis"] in ("modeled_price", "client_estimate") for c in priced) else None,
        "currentProviderChargeUsd": current_total if all(c["costBasis"] == "provider_charge" for c in priced) else None,
        "auxiliaryAndRetryCostIncludedUsd": _sum_known([c["costUsd"] for c in priced if c["category"] != "primary"], complete=complete),
        "extraOverheadUsd": overhead_total,
        "netModeledSavingsUsd": net,
        "currency": "USD",
    }
