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


class ObservedExecution(BaseModel):
    """Caller-recorded metadata for one actual attempt in a registered pair."""

    model_config = ConfigDict(extra="forbid", strict=True)
    task_id: StrictStr = Field(min_length=1)
    snapshot_hash: StrictStr = Field(min_length=1)
    candidate_arm_id: StrictStr = Field(min_length=1)
    arm_id: StrictStr = Field(min_length=1)
    attempt_index: StrictInt = Field(ge=0)
    run_order_index: StrictInt = Field(ge=0, le=1)
    execution_sequence: StrictInt = Field(ge=0)
    seed: StrictInt = Field(ge=0)
    manifest_sha256: StrictStr = Field(min_length=1)
    assignment_sha256: StrictStr = Field(min_length=1)
    client: StrictStr | None = None
    client_version: StrictStr | None = None
    model: StrictStr | None = None
    model_version: StrictStr | None = None
    runtime: StrictStr | None = None
    runtime_version: StrictStr | None = None
    implementation_version: StrictStr | None = None
    configuration: dict[str, Any] | None = None
    cache_state: dict[str, Any] | None = None
    kind: ArmKind | None = None
    components: tuple[OptimizerKind, ...] | None = None


def audit_execution_adherence(
    protocol: BenchmarkProtocol, observations: list[ObservedExecution],
) -> dict[str, Any]:
    """Audit supplied execution metadata without inferring outcomes or running tasks."""
    plan = assignment_plan(protocol)
    tasks = {task.fixture.task_id: task for task in protocol.tasks}
    arms = {arm.arm_id: arm for arm in protocol.arms}
    assignments = {(a["task_id"], a["candidate_arm_id"]): a
                   for a in plan["assignments"]}
    counts: dict[str, dict[str, int]] = {candidate: {} for candidate in
                                         protocol.planned_pairs_by_candidate}
    seen: dict[tuple[str, str, str], list[int]] = {}
    sequences: dict[tuple[str, str, str], list[int]] = {}
    invalid_pairs: set[tuple[str, str]] = set()
    sequence_owner: dict[int, int] = {}
    issues: list[dict[str, Any]] = []

    def issue(code: str, index: int | None, **details: Any) -> None:
        issues.append({"code": code, "observation_index": index, **details})
        if index is not None:
            obs = observations[index]
            invalid_pairs.add((obs.task_id, obs.candidate_arm_id))
        elif "task_id" in details and "candidate_arm_id" in details:
            invalid_pairs.add((details["task_id"], details["candidate_arm_id"]))

    for index, obs in enumerate(observations):
        key = (obs.task_id, obs.candidate_arm_id)
        assignment = assignments.get(key)
        task = tasks.get(obs.task_id)
        arm = arms.get(obs.arm_id)
        if obs.execution_sequence in sequence_owner:
            issue("duplicate_execution_sequence", index,
                  first_observation_index=sequence_owner[obs.execution_sequence])
            first = observations[sequence_owner[obs.execution_sequence]]
            invalid_pairs.add((first.task_id, first.candidate_arm_id))
        else:
            sequence_owner[obs.execution_sequence] = index
        if assignment is None or obs.arm_id not in (
            protocol.baseline_arm_id, obs.candidate_arm_id
        ):
            issue("excess_observation", index, task_id=obs.task_id,
                  candidate_arm_id=obs.candidate_arm_id, arm_id=obs.arm_id)
            continue
        seen.setdefault((obs.task_id, obs.candidate_arm_id, obs.arm_id), []).append(
            obs.attempt_index)
        sequences.setdefault((obs.task_id, obs.candidate_arm_id, obs.arm_id), []).append(
            obs.execution_sequence)
        if task is None or obs.snapshot_hash != task.fixture.fixture_id:
            issue("snapshot_mismatch", index)
        if obs.seed != protocol.seed or obs.run_order_index != assignment["run_order"].index(obs.arm_id):
            issue("seed_or_order_mismatch", index)
        if obs.manifest_sha256 != plan["manifest_sha256"] or obs.assignment_sha256 != plan["assignment_sha256"]:
            issue("registration_hash_mismatch", index)
        if arm is None:
            issue("unknown_arm", index)
            continue
        for field in ("client", "client_version", "model", "model_version", "runtime",
                      "runtime_version", "implementation_version", "configuration",
                      "cache_state", "kind", "components"):
            actual = getattr(obs, field)
            expected = getattr(arm, field)
            if actual is None:
                issue("unknown_metadata", index, field=field)
            elif actual != expected:
                issue("arm_metadata_mismatch", index, field=field)

    for (task_id, candidate), assignment in assignments.items():
        for arm_id in assignment["run_order"]:
            indices = seen.get((task_id, candidate, arm_id), [])
            if not indices:
                issue("missing_observation", None, task_id=task_id,
                      candidate_arm_id=candidate, arm_id=arm_id)
            elif sorted(indices) != list(range(len(indices))):
                issue("attempt_sequence_invalid", None, task_id=task_id,
                      candidate_arm_id=candidate, arm_id=arm_id)
            elif len(indices) > 1:
                records = [(obs.attempt_index, obs.execution_sequence) for obs in observations
                           if (obs.task_id, obs.candidate_arm_id, obs.arm_id)
                           == (task_id, candidate, arm_id)]
                if [sequence for _, sequence in sorted(records)] != sorted(sequences[
                    (task_id, candidate, arm_id)]):
                    issue("attempt_chronology_mismatch", None, task_id=task_id,
                          candidate_arm_id=candidate, arm_id=arm_id)
        first_arm, second_arm = assignment["run_order"]
        first_sequences = sequences.get((task_id, candidate, first_arm), [])
        second_sequences = sequences.get((task_id, candidate, second_arm), [])
        if first_sequences and second_sequences and max(first_sequences) >= min(second_sequences):
            issue("arm_chronology_mismatch", None, task_id=task_id,
                  candidate_arm_id=candidate)
        if ((task_id, candidate) not in invalid_pairs
                and all(seen.get((task_id, candidate, arm_id)) for arm_id in assignment["run_order"])):
            stratum = f"{assignment['locale']}/{assignment['stratum']}"
            counts[candidate][stratum] = counts[candidate].get(stratum, 0) + 1
    for candidate, planned in protocol.planned_pairs_by_candidate.items():
        for stratum, denominator in planned.items():
            if counts[candidate].get(stratum, 0) != denominator:
                issue("denominator_mismatch", None, candidate_arm_id=candidate,
                      stratum=stratum, planned=denominator,
                      observed=counts[candidate].get(stratum, 0))
    return {
        "scope": "offline_execution_adherence_audit",
        "protocol_id": protocol.protocol_id,
        "manifest_sha256": plan["manifest_sha256"],
        "assignment_sha256": plan["assignment_sha256"],
        "valid": not issues,
        "issues": issues,
        "planned_pairs_by_candidate": protocol.planned_pairs_by_candidate,
        "observed_complete_pairs_by_candidate": counts,
        "quality_result": None,
        "economy_result": None,
        "efficacy_claim": None,
    }
