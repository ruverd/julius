"""Offline, auditable suspension decisions for one optimization scope."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    project_id: StrictStr = Field(min_length=1)
    model_id: StrictStr = Field(min_length=1)
    strategy_id: StrictStr = Field(min_length=1)
    strategy_version: StrictStr = Field(min_length=1)


class GuardPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    version: StrictStr = Field(min_length=1)
    minimum_samples: StrictInt = Field(ge=1)
    max_error_rate: StrictFloat = Field(ge=0, le=1, allow_inf_nan=False)
    max_recovery_rate: StrictFloat = Field(ge=0, le=1, allow_inf_nan=False)
    max_rework_rate: StrictFloat = Field(ge=0, le=1, allow_inf_nan=False)
    max_mean_latency_ms: StrictFloat = Field(ge=0, allow_inf_nan=False)
    min_total_net_savings_usd: StrictFloat = Field(allow_inf_nan=False)


class TaskOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    scope: Scope
    sequence: StrictInt = Field(ge=0)
    task_id: StrictStr = Field(min_length=1)
    error: StrictBool | None
    recovery_used: StrictBool | None
    rework_needed: StrictBool | None
    latency_ms: StrictFloat | None = Field(ge=0, allow_inf_nan=False)
    net_savings_usd: StrictFloat | None = Field(allow_inf_nan=False)


class ManualAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    scope: Scope
    sequence: StrictInt = Field(ge=0)
    action: Literal["disable", "reenable"]
    reason: StrictStr = Field(min_length=1)


def decide_suspension(
    scope: Scope, policy: GuardPolicy, outcomes: Sequence[TaskOutcome],
    actions: Sequence[ManualAction] = (),
) -> dict[str, Any]:
    """Decide from supplied records only; never execute or mutate an external system."""
    records: list[TaskOutcome | ManualAction] = [*outcomes, *actions]
    if any(record.scope != scope for record in records):
        raise ValueError("Record scope does not match decision scope")
    sequences = [record.sequence for record in records]
    if len(sequences) != len(set(sequences)):
        raise ValueError("Sequences must be unique within a scope")
    task_ids = [record.task_id for record in outcomes]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("Each task outcome must have a unique task ID")
    latest_action = max(actions, key=lambda item: item.sequence, default=None)
    since = latest_action.sequence if latest_action is not None else -1
    current = [item for item in outcomes if item.sequence > since]
    count = len(current)
    sufficient = count >= policy.minimum_samples
    metrics: dict[str, dict[str, int | float | None]] = {}
    for field, label in (("error", "error_rate"), ("recovery_used", "recovery_rate"),
                         ("rework_needed", "rework_rate"),
                         ("latency_ms", "mean_latency_ms"),
                         ("net_savings_usd", "total_net_savings_usd")):
        values = [getattr(item, field) for item in current]
        known = [value for value in values if value is not None]
        value: float | None = None
        if sufficient and len(known) == count:
            total = sum(float(item) for item in known)
            value = total if label == "total_net_savings_usd" else total / count
        metrics[label] = {"known_samples": len(known), "value": value}
    checks = (
        ("error_rate", "above_max_error_rate", policy.max_error_rate, "max"),
        ("recovery_rate", "above_max_recovery_rate", policy.max_recovery_rate, "max"),
        ("rework_rate", "above_max_rework_rate", policy.max_rework_rate, "max"),
        ("mean_latency_ms", "above_max_mean_latency_ms", policy.max_mean_latency_ms, "max"),
        ("total_net_savings_usd", "below_min_total_net_savings_usd",
         policy.min_total_net_savings_usd, "min"),
    )
    reasons = []
    for name, reason, threshold, direction in checks:
        value = metrics[name]["value"]
        if value is not None and (
            (direction == "max" and value > threshold)
            or (direction == "min" and value < threshold)
        ):
            reasons.append(reason)
    if latest_action is not None and latest_action.action == "disable":
        status = "manual_disabled"
    elif reasons:
        status = "suspended"
    elif not sufficient or any(metric["value"] is None for metric in metrics.values()):
        status = "insufficient_evidence"
    else:
        status = "enabled"
    return {
        "scope": scope.model_dump(), "policy_version": policy.version,
        "status": status, "suspended": status in ("manual_disabled", "suspended"),
        "reasons": reasons, "sample_count": count,
        "minimum_samples": policy.minimum_samples,
        "metrics": metrics,
        "latest_manual_action": latest_action.model_dump() if latest_action else None,
        "record_sequences": sorted(sequences),
    }
