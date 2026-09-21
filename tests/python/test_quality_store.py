import os

import pytest

from julius.quality_guard import GuardPolicy, ManualAction, Scope, TaskOutcome
from julius.quality_store import QualityStore
from julius.sdk import Julius


SCOPE = Scope(project_id="p", model_id="m", strategy_id="repeated-lines", strategy_version="2")
POLICY = GuardPolicy(
    version="1", minimum_samples=2, max_error_rate=0.25,
    max_recovery_rate=0.5, max_rework_rate=0.5,
    max_mean_latency_ms=100.0, min_total_net_savings_usd=0.0,
)


def outcome(sequence, task, **changes):
    data = dict(scope=SCOPE, sequence=sequence, task_id=task, error=False,
                recovery_used=False, rework_needed=False,
                latency_ms=10.0, net_savings_usd=1.0)
    data.update(changes)
    return TaskOutcome(**data)


def test_store_persists_atomic_decisions_and_manual_state(tmp_path):
    path = tmp_path / "quality.sqlite"
    with QualityStore(path) as store:
        assert store.append(outcome(1, "a"), POLICY)["status"] == "insufficient_evidence"
        assert store.append(outcome(2, "b"), POLICY)["status"] == "enabled"
        with pytest.raises(ValueError, match="sequence must increase"):
            store.append(outcome(2, "duplicate"), POLICY)
        assert len(store.history(SCOPE)["outcomes"]) == 2
        assert store.append(ManualAction(
            scope=SCOPE, sequence=3, action="disable", reason="operator"), POLICY,
        )["status"] == "manual_disabled"
    with QualityStore(path) as store:
        assert store.decision(SCOPE, POLICY)["status"] == "manual_disabled"
        assert store.append(ManualAction(
            scope=SCOPE, sequence=4, action="reenable", reason="reviewed"), POLICY,
        )["status"] == "insufficient_evidence"
        assert store.append(outcome(5, "c"), POLICY)["status"] == "insufficient_evidence"
        assert store.append(outcome(6, "d"), POLICY)["status"] == "enabled"


def test_sdk_guard_blocks_before_artifact_and_allows_explicitly_enabled_scope(tmp_path):
    text = "\n".join([
        "ordinary neutral line with enough characters for deterministic reduction and more detail"
    ] * 6)
    context = {"projectId": "p", "modelId": "m", "content": text, "category": "tool_output"}
    policy = {"mode": "safe", "approved": True, "version": "1.0.0"}
    with Julius(tmp_path) as julius:
        with pytest.raises(RuntimeError, match="insufficient_evidence"):
            julius.optimize(context, policy, quality_scope=SCOPE, quality_policy=POLICY)
        assert list((tmp_path / "artifacts").rglob("*.txt")) == []
        with QualityStore(tmp_path / "quality.sqlite") as store:
            store.append(outcome(1, "a"), POLICY)
            store.append(outcome(2, "b"), POLICY)
        assert julius.optimize(context, policy, quality_scope=SCOPE, quality_policy=POLICY)[
            "receipt"]["applied"] is True
        with QualityStore(tmp_path / "quality.sqlite") as store:
            store.append(outcome(3, "c", error=True), POLICY)
        with pytest.raises(RuntimeError, match="suspended"):
            julius.optimize(context, policy, quality_scope=SCOPE, quality_policy=POLICY)


def test_sdk_default_optimization_remains_available(tmp_path):
    with Julius(tmp_path) as julius:
        result = julius.optimize(
            {"projectId": "p", "content": "short", "category": "tool_output"},
            {"mode": "observe", "version": "1.0.0"},
        )
    assert result["original"] is None


def test_sdk_guard_store_access_error_blocks_before_artifact(tmp_path, monkeypatch):
    def fail(_path):
        raise OSError("unavailable")

    monkeypatch.setattr("julius.sdk.QualityStore", fail)
    with Julius(tmp_path) as julius:
        with pytest.raises(RuntimeError, match="guard unavailable"):
            julius.optimize(
                {"projectId": "p", "modelId": "m", "content": "short", "category": "tool_output"},
                {"mode": "observe", "version": "1.0.0"},
                quality_scope=SCOPE, quality_policy=POLICY,
            )
    assert list((tmp_path / "artifacts").rglob("*.txt")) == []


def test_sdk_guard_rejects_missing_or_wrong_model_identity(tmp_path):
    with Julius(tmp_path) as julius:
        for model_id in (None, "other"):
            with pytest.raises(ValueError, match="matching model ID"):
                julius.optimize(
                    {"projectId": "p", "modelId": model_id, "content": "short", "category": "tool_output"},
                    {"mode": "safe", "approved": True, "version": "1.0.0"},
                    quality_scope=SCOPE, quality_policy=POLICY,
                )


def test_sdk_guard_rejects_unrelated_strategy_scope(tmp_path):
    wrong = SCOPE.model_copy(update={"strategy_id": "other-strategy"})
    with Julius(tmp_path) as julius:
        with pytest.raises(ValueError, match="optimizer strategy"):
            julius.optimize(
                {"projectId": "p", "modelId": "m", "content": "short", "category": "tool_output"},
                {"mode": "safe", "approved": True, "version": "1.0.0"},
                quality_scope=wrong, quality_policy=POLICY,
            )
    assert list((tmp_path / "artifacts").rglob("*.txt")) == []


def test_store_file_and_wal_are_owner_only(tmp_path):
    path = tmp_path / "quality.sqlite"
    with QualityStore(path) as store:
        store.append(outcome(1, "a"), POLICY)
        assert path.stat().st_mode & 0o077 == 0
        wal = tmp_path / "quality.sqlite-wal"
        assert wal.exists()
        assert wal.stat().st_mode & 0o077 == 0


def test_store_rejects_symlink_and_unsafe_existing_modes(tmp_path):
    target = tmp_path / "target.sqlite"
    target.write_bytes(b"")
    link = tmp_path / "quality.sqlite"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="Unsafe quality store file"):
        QualityStore(link)
    link.unlink()
    target.rename(link)
    os.chmod(link, 0o644)
    with pytest.raises(ValueError, match="Unsafe quality store file"):
        QualityStore(link)
    os.chmod(link, 0o600)
    sidecar = tmp_path / "quality.sqlite-wal"
    sidecar.write_bytes(b"")
    os.chmod(sidecar, 0o644)
    with pytest.raises(ValueError, match="Unsafe quality store file"):
        QualityStore(link)


def test_v1_outcomes_cannot_clear_v2_optimizer(tmp_path):
    old_scope = SCOPE.model_copy(update={"strategy_version": "1"})
    with QualityStore(tmp_path / "quality.sqlite") as store:
        store.append(outcome(1, "old-a", scope=old_scope), POLICY)
        store.append(outcome(2, "old-b", scope=old_scope), POLICY)
        assert store.decision(old_scope, POLICY)["status"] == "enabled"
        assert store.decision(SCOPE, POLICY)["status"] == "insufficient_evidence"
    with Julius(tmp_path) as julius:
        context = {"projectId": "p", "modelId": "m", "content": "short", "category": "tool_output"}
        policy = {"mode": "safe", "approved": True, "version": "1.0.0"}
        with pytest.raises(ValueError, match="optimizer strategy"):
            julius.optimize(context, policy, quality_scope=old_scope, quality_policy=POLICY)
        with pytest.raises(RuntimeError, match="insufficient_evidence"):
            julius.optimize(context, policy, quality_scope=SCOPE, quality_policy=POLICY)
    assert list((tmp_path / "artifacts").rglob("*.txt")) == []
