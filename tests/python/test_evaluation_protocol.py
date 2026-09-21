import pytest
from pydantic import ValidationError

from julius.evaluation_protocol import (
    BenchmarkProtocol, ProtocolArm, ProtocolTask, SuccessCriterion, assignment_plan,
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
