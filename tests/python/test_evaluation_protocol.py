import pytest
from pydantic import ValidationError

from julius.evaluation_protocol import (
    BenchmarkProtocol, ObservedExecution, ProtocolArm, ProtocolTask, SuccessCriterion,
    assignment_plan, audit_execution_adherence,
)
from julius.evaluation_runner import FrozenFixture


def registered(**changes):
    arms = [ProtocolArm(
        arm_id=name, kind=kind, client="client", client_version="1.0", model="model",
        model_version="2026-09", runtime="runtime", runtime_version="3.11",
        implementation_version="abc123", configuration={"mode": kind},
        cache_state={"state": "cold"},
    ) for name, kind in [("base", "native"), ("head", "headroom"), ("rtk", "rtk"),
                         ("context", "context_mode")]]
    tasks = []
    for locale in ("en", "pt"):
        for index in range(2):
            task_id = f"{locale}-{index}"
            snapshot = {"prompt": task_id}
            tasks.append(ProtocolTask(
                fixture=FrozenFixture(task_id=task_id,
                                      fixture_id=FrozenFixture.digest(task_id, snapshot),
                                      snapshot=snapshot),
                locale=locale, stratum="general", eligible_arm_ids=tuple(a.arm_id for a in arms),
            ))
    data = dict(schema_version="1", protocol_id="benchmark-1", phase="pilot", seed=42,
                planned_pairs_by_candidate={name: {"en/general": 2, "pt/general": 2}
                                            for name in ("head", "rtk", "context")},
                baseline_arm_id="base", arms=tuple(arms),
                tasks=tuple(tasks), success_criterion=SuccessCriterion(
                    quality_metric="success_rate", noninferiority_margin=0.05,
                    efficiency_metric="input_tokens", minimum_relative_reduction=0.10,
                    grading_rule="Exact answer match against frozen key"))
    data.update(changes)
    return BenchmarkProtocol(**data)


def test_plan_reproducible_complete_and_contains_no_result():
    protocol = registered()
    first = assignment_plan(protocol)
    assert first == assignment_plan(protocol)
    assert first["quality_result"] is None and first["efficacy_claim"] is None
    assert len(first["assignments"]) == 12
    assert {a["locale"] for a in first["assignments"]} == {"en", "pt"}
    assert {a["candidate_arm_id"] for a in first["assignments"]} == {"head", "rtk", "context"}
    assert all(set(a["run_order"]) == {"base", a["candidate_arm_id"]}
               for a in first["assignments"])
    assert first["manifest_sha256"] != assignment_plan(registered(seed=43))["manifest_sha256"]


def test_rejects_cherry_picked_tasks_and_ineligible_arms():
    protocol = registered()
    with pytest.raises(ValidationError, match="sample counts"):
        registered(tasks=protocol.tasks[:-1])
    partial = protocol.tasks[0].model_copy(update={"eligible_arm_ids": ("base", "head")})
    with pytest.raises(ValidationError, match="sample counts"):
        registered(tasks=(partial, *protocol.tasks[1:]))
    with pytest.raises(ValidationError, match="baseline"):
        registered(tasks=(protocol.tasks[0].model_copy(
            update={"eligible_arm_ids": ("head", "rtk")}), *protocol.tasks[1:]))
    with pytest.raises(ValidationError, match="sample counts"):
        registered(tasks=tuple(t for t in protocol.tasks if t.locale == "en"))


def test_rejects_missing_baseline_arm_version_and_criterion():
    protocol = registered()
    with pytest.raises(ValidationError, match="native arm"):
        registered(baseline_arm_id="head")
    with pytest.raises(ValidationError):
        ProtocolArm.model_validate({k: v for k, v in protocol.arms[0].model_dump().items()
                                    if k != "client_version"})
    with pytest.raises(ValidationError):
        BenchmarkProtocol.model_validate({k: v for k, v in protocol.model_dump().items()
                                          if k != "success_criterion"})


def test_snapshot_change_invalidates_registration():
    protocol = registered()
    task = protocol.tasks[0]
    with pytest.raises(ValidationError, match="Fixture ID"):
        FrozenFixture(task_id=task.fixture.task_id, fixture_id=task.fixture.fixture_id,
                      snapshot={"prompt": "changed"})


def test_modality_specific_pairs_keep_declared_denominators():
    protocol = registered()
    tasks = tuple(task.model_copy(update={"eligible_arm_ids": ("base", "head")})
                  if task.fixture.task_id.endswith("-0") else task.model_copy(
                      update={"eligible_arm_ids": ("base", "rtk", "context")})
                  for task in protocol.tasks)
    counts = {"head": {"en/general": 1, "pt/general": 1},
              "rtk": {"en/general": 1, "pt/general": 1},
              "context": {"en/general": 1, "pt/general": 1}}
    plan = assignment_plan(registered(tasks=tasks, planned_pairs_by_candidate=counts))
    assert len(plan["assignments"]) == 6
    assert all(a["candidate_arm_id"] in next(
        task.eligible_arm_ids for task in tasks if task.fixture.task_id == a["task_id"])
        for a in plan["assignments"])
    with pytest.raises(ValidationError, match="sample counts"):
        registered(tasks=tasks, planned_pairs_by_candidate={**counts, "head": {"en/general": 1}})


def test_confirmatory_requires_rationale_without_claiming_power():
    with pytest.raises(ValidationError, match="sample-size rationale"):
        registered(phase="confirmatory")
    protocol = registered(phase="confirmatory", sample_size_rationale="Pilot variance estimate; target 80% power")
    assert assignment_plan(protocol)["efficacy_claim"] is None


def test_same_kind_configurations_and_combination_are_distinct_arms():
    protocol = registered()
    second_head = protocol.arms[1].model_copy(update={"arm_id": "head-v2",
        "configuration": {"mode": "headroom", "setting": 2}})
    combination = protocol.arms[1].model_copy(update={"arm_id": "head-rtk",
        "kind": "combination", "components": ("headroom", "rtk"),
        "configuration": {"mode": "combined"}})
    arms = (*protocol.arms, second_head, combination)
    tasks = tuple(task.model_copy(update={"eligible_arm_ids":
        (*task.eligible_arm_ids, "head-v2", "head-rtk")}) for task in protocol.tasks)
    counts = {**protocol.planned_pairs_by_candidate,
              "head-v2": {"en/general": 2, "pt/general": 2},
              "head-rtk": {"en/general": 2, "pt/general": 2}}
    plan = assignment_plan(registered(arms=arms, tasks=tasks,
                                      planned_pairs_by_candidate=counts))
    assert len(plan["assignments"]) == 20
    assert {a["candidate_arm_id"] for a in plan["assignments"]} >= {"head-v2", "head-rtk"}


def test_combination_components_are_validated():
    arm = registered().arms[1]
    with pytest.raises(ValidationError, match="two or three distinct"):
        type(arm).model_validate({**arm.model_dump(), "kind": "combination",
                                  "components": ("headroom", "headroom")})
    with pytest.raises(ValidationError, match="Only combination"):
        type(arm).model_validate({**arm.model_dump(), "components": ("rtk",)})


def observed(protocol):
    plan = assignment_plan(protocol)
    arms = {arm.arm_id: arm for arm in protocol.arms}
    return [ObservedExecution(
        task_id=assignment["task_id"], snapshot_hash=assignment["snapshot_hash"],
        candidate_arm_id=assignment["candidate_arm_id"], arm_id=arm_id,
        attempt_index=0, run_order_index=position, seed=protocol.seed,
        manifest_sha256=plan["manifest_sha256"],
        assignment_sha256=plan["assignment_sha256"],
        **{field: getattr(arms[arm_id], field) for field in (
            "client", "client_version", "model", "model_version", "runtime",
            "runtime_version", "implementation_version", "configuration",
            "cache_state", "kind", "components")},
    ) for assignment in plan["assignments"]
        for position, arm_id in enumerate(assignment["run_order"])]


def test_complete_observed_execution_audits_without_claim():
    protocol = registered()
    result = audit_execution_adherence(protocol, observed(protocol))
    assert result["valid"] is True
    assert result["issues"] == []
    assert result["observed_complete_pairs_by_candidate"] == protocol.planned_pairs_by_candidate
    assert result["quality_result"] is None
    assert result["economy_result"] is None


def test_audit_finds_missing_excess_and_denominator_changes():
    protocol = registered()
    rows = observed(protocol)
    rows.pop()
    rows.append(rows[0].model_copy(update={"task_id": "unregistered"}))
    result = audit_execution_adherence(protocol, rows)
    codes = {item["code"] for item in result["issues"]}
    assert result["valid"] is False
    assert {"missing_observation", "excess_observation", "denominator_mismatch"} <= codes


def test_audit_finds_snapshot_environment_order_and_unknowns():
    protocol = registered()
    rows = observed(protocol)
    rows[0] = rows[0].model_copy(update={
        "snapshot_hash": "wrong", "seed": 17, "run_order_index": 1 - rows[0].run_order_index,
        "cache_state": {"state": "warm"}, "model_version": None,
    })
    result = audit_execution_adherence(protocol, rows)
    codes = {item["code"] for item in result["issues"]}
    assert {"snapshot_mismatch", "seed_or_order_mismatch", "arm_metadata_mismatch",
            "unknown_metadata"} <= codes


def test_audit_rejects_duplicate_attempt_indices_and_changed_registration():
    protocol = registered()
    rows = observed(protocol)
    rows.append(rows[0])
    rows[1] = rows[1].model_copy(update={"manifest_sha256": "wrong"})
    codes = {item["code"] for item in audit_execution_adherence(protocol, rows)["issues"]}
    assert "attempt_sequence_invalid" in codes
    assert "registration_hash_mismatch" in codes
