from julius.artifacts import ArtifactStore
from julius.claude_hooks import post_tool_use


POLICY = {"mode": "safe", "approved": True, "version": "1.0.0"}
LINE = "ordinary neutral line with enough characters for deterministic reduction and more detail"
TEXT = "\n".join([LINE] * 6)


def _event(stdout=TEXT):
    return {
        "hook_event_name": "PostToolUse", "tool_name": "Bash",
        "tool_input": {"command": "printf fixture"},
        "tool_response": {"stdout": stdout, "stderr": "", "interrupted": False, "isImage": False},
    }


def test_candidate_callback_sees_verified_artifact_and_estimate(tmp_path):
    store = ArtifactStore(tmp_path)
    seen = []

    def record(artifact, receipt):
        assert store.get("project", artifact["id"]) == TEXT
        seen.append((artifact, receipt))

    output = post_tool_use(
        _event(), policy=POLICY, store=store, project_id="project",
        recovery_available=True, candidate_receipt=record,
    )
    assert output is not None
    artifact, receipt = seen[0]
    assert len(seen) == 1
    assert receipt["lineage"]["originalArtifactId"] == artifact["id"]
    assert receipt["beforeBytes"] > receipt["afterBytes"]
    assert receipt["evidence"] == "heuristic_estimate"
    assert receipt["realizedSavings"] is None


def test_callback_failure_passes_through_and_cleans_artifact(tmp_path):
    store = ArtifactStore(tmp_path)

    def fail(_artifact, _receipt):
        raise RuntimeError("ledger unavailable")

    assert post_tool_use(
        _event(), policy=POLICY, store=store, project_id="project",
        recovery_available=True, candidate_receipt=fail,
    ) is None
    assert list(tmp_path.rglob("*.txt")) == []
    assert list(tmp_path.rglob("*.json")) == []


def test_callback_is_not_called_for_pass_through(tmp_path):
    store = ArtifactStore(tmp_path)
    calls = []
    assert post_tool_use(
        _event("short"), policy=POLICY, store=store, project_id="project",
        recovery_available=True, candidate_receipt=lambda a, r: calls.append((a, r)),
    ) is None
    assert calls == []
