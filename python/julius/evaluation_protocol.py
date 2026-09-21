"""Frozen, offline benchmark registration and deterministic paired assignment."""

from __future__ import annotations

import hashlib
import json
import random
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from .evaluation_runner import FrozenFixture


OptimizerKind = Literal["headroom", "rtk", "context_mode"]
ArmKind = Literal["native", "headroom", "rtk", "context_mode", "combination"]
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
    components: tuple[OptimizerKind, ...] = ()
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
        if self.kind == "combination":
            if not 2 <= len(self.components) <= 3 or len(set(self.components)) != len(self.components):
                raise ValueError("Combination requires two or three distinct optimizer components")
        elif self.components:
            raise ValueError("Only combination arms may declare components")
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
    planned_pairs_by_candidate: dict[str, dict[str, StrictInt]] = Field(min_length=1)
    sample_size_rationale: StrictStr | None = None
    baseline_arm_id: StrictStr = Field(min_length=1)
    arms: tuple[ProtocolArm, ...] = Field(min_length=2)
    tasks: tuple[ProtocolTask, ...] = Field(min_length=2)
    success_criterion: SuccessCriterion

    @model_validator(mode="after")
    def verify_registration(self) -> BenchmarkProtocol:
        arms = {arm.arm_id: arm for arm in self.arms}
        if len(arms) != len(self.arms):
            raise ValueError("Arm IDs must be unique")
        if self.baseline_arm_id not in arms or arms[self.baseline_arm_id].kind != "native":
            raise ValueError("Baseline must be a registered native arm")
        if len({task.fixture.task_id for task in self.tasks}) != len(self.tasks):
            raise ValueError("Task IDs must be unique")
        if len({task.fixture.fixture_id for task in self.tasks}) != len(self.tasks):
            raise ValueError("Snapshot hashes must be unique")
        if self.phase == "confirmatory" and not (self.sample_size_rationale or "").strip():
            raise ValueError("Confirmatory protocol requires a sample-size rationale")
        candidates = set(arms) - {self.baseline_arm_id}
        if set(self.planned_pairs_by_candidate) != candidates:
            raise ValueError("Planned sample counts must name every candidate arm")
        strata: dict[str, dict[str, int]] = {candidate: {} for candidate in candidates}
        for task in self.tasks:
            eligible = task.eligible_arm_ids
            if (len(set(eligible)) != len(eligible) or self.baseline_arm_id not in eligible
                    or not set(eligible).issubset(arms) or len(eligible) < 2):
                raise ValueError("Each task needs the baseline and at least one registered candidate")
            key = f"{task.locale}/{task.stratum}"
            for candidate in set(eligible) - {self.baseline_arm_id}:
                strata[candidate][key] = strata[candidate].get(key, 0) + 1
        for candidate, actual in strata.items():
            planned = self.planned_pairs_by_candidate[candidate]
            if (set(key.split("/", 1)[0] for key in planned) != {"en", "pt"}
                    or any(type(count) is not int or count < 1 for count in planned.values())
                    or planned != actual):
                raise ValueError("Candidate locale strata must match predeclared sample counts")
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
            if candidate not in task.eligible_arm_ids:
                continue
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
