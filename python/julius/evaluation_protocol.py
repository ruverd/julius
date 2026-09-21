"""Frozen, offline benchmark registration and deterministic paired assignment."""

from __future__ import annotations

import hashlib
import json
import random
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from .evaluation_runner import FrozenFixture


ArmKind = Literal["native", "headroom", "rtk", "context_mode"]
Locale = Literal["en", "pt"]
Phase = Literal["pilot", "confirmatory"]
EfficiencyMetric = Literal["input_tokens", "cost_usd", "latency_ms"]


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


class ProtocolTask(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    fixture: FrozenFixture
    locale: Locale
    stratum: StrictStr = Field(min_length=1)
    eligible_arm_ids: tuple[StrictStr, ...] = Field(min_length=2)


class ProtocolArm(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    arm_id: StrictStr = Field(min_length=1)
    kind: ArmKind
    client: StrictStr = Field(min_length=1)
    client_version: StrictStr = Field(min_length=1)
    model: StrictStr = Field(min_length=1)
    model_version: StrictStr = Field(min_length=1)
    runtime: StrictStr = Field(min_length=1)
    runtime_version: StrictStr = Field(min_length=1)
    implementation_version: StrictStr = Field(min_length=1)
    configuration: dict[str, Any] = Field(min_length=1)
    cache_state: dict[str, Any] = Field(min_length=1)

    @model_validator(mode="after")
    def json_state(self) -> ProtocolArm:
        _canonical(self.configuration)
        _canonical(self.cache_state)
        return self


class SuccessCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    quality_metric: Literal["success_rate"]
    noninferiority_margin: float = Field(ge=0, le=1, allow_inf_nan=False)
    efficiency_metric: EfficiencyMetric
    minimum_relative_reduction: float = Field(ge=0, le=1, allow_inf_nan=False)
    grading_rule: StrictStr = Field(min_length=1)


class BenchmarkProtocol(BaseModel):
    """Registration only: no observed outcomes or efficacy assertion."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["1"]
    protocol_id: StrictStr = Field(min_length=1)
    phase: Phase
    seed: StrictInt = Field(ge=0)
    planned_pairs_per_stratum: StrictInt = Field(ge=1)
    baseline_arm_id: StrictStr = Field(min_length=1)
    arms: tuple[ProtocolArm, ...] = Field(min_length=2)
    tasks: tuple[ProtocolTask, ...] = Field(min_length=2)
    success_criterion: SuccessCriterion

    @model_validator(mode="after")
    def verify_registration(self) -> BenchmarkProtocol:
        arms = {arm.arm_id: arm for arm in self.arms}
        if len(arms) != len(self.arms) or len({arm.kind for arm in self.arms}) != len(self.arms):
            raise ValueError("Arm IDs and kinds must be unique")
        if self.baseline_arm_id not in arms or arms[self.baseline_arm_id].kind != "native":
            raise ValueError("Baseline must be a registered native arm")
        if len({task.fixture.task_id for task in self.tasks}) != len(self.tasks):
            raise ValueError("Task IDs must be unique")
        if len({task.fixture.fixture_id for task in self.tasks}) != len(self.tasks):
            raise ValueError("Snapshot hashes must be unique")
        strata: dict[tuple[str, str], int] = {}
        for task in self.tasks:
            eligible = task.eligible_arm_ids
            if (len(set(eligible)) != len(eligible) or set(eligible) != set(arms)
                    or self.baseline_arm_id not in eligible):
                raise ValueError("Every frozen task must be eligible for every registered arm")
            key = (task.locale, task.stratum)
            strata[key] = strata.get(key, 0) + 1
        if {locale for locale, _ in strata} != {"en", "pt"}:
            raise ValueError("English and Portuguese task strata are both required")
        if any(count != self.planned_pairs_per_stratum for count in strata.values()):
            raise ValueError("Every locale stratum must match planned sample size")
        return self


def assignment_plan(protocol: BenchmarkProtocol) -> dict[str, Any]:
    """Return a canonical receipt and seeded order; execute nothing."""
    manifest = protocol.model_dump(mode="json")
    manifest_hash = hashlib.sha256(_canonical(manifest)).hexdigest()
    rng = random.Random(protocol.seed)
    assignments: list[dict[str, Any]] = []
    candidates = sorted(arm.arm_id for arm in protocol.arms
                        if arm.arm_id != protocol.baseline_arm_id)
    for task in sorted(protocol.tasks, key=lambda item: (item.locale, item.stratum,
                                                         item.fixture.task_id)):
        for candidate in candidates:
            order = [protocol.baseline_arm_id, candidate]
            rng.shuffle(order)
            assignments.append({
                "task_id": task.fixture.task_id,
                "snapshot_hash": task.fixture.fixture_id,
                "locale": task.locale,
                "stratum": task.stratum,
                "candidate_arm_id": candidate,
                "run_order": order,
            })
    plan_hash = hashlib.sha256(_canonical(assignments)).hexdigest()
    return {
        "scope": "offline_protocol_registration",
        "phase": protocol.phase,
        "protocol_id": protocol.protocol_id,
        "manifest_sha256": manifest_hash,
        "assignment_sha256": plan_hash,
        "assignments": assignments,
        "quality_result": None,
        "efficacy_claim": None,
    }
