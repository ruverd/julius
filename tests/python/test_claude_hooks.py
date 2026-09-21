from julius.artifacts import ArtifactStore
from julius.claude_hooks import post_tool_use


POLICY = {"mode": "safe", "approved": True, "version": "1.0.0"}
LINE = "ordinary neutral line with enough characters for deterministic reduction and more detail"
TEXT = "\n".join([LINE] * 6)


def event(**changes):
    value = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "printf fixture"},
        "tool_response": {
            "stdout": TEXT,
            "stderr": "",
            "interrupted": False,
            "isImage": False,
        },
    }
    value.update(changes)
    return value


def test_replacement_is_recoverable_and_preserves_response(tmp_path):
    store = ArtifactStore(tmp_path)
    original = event()
    result = post_tool_use(original, policy=POLICY, store=store, project_id="test", recovery_available=True)
    assert result is not None
    output = result["hookSpecificOutput"]["updatedToolOutput"]
    assert output["stderr"] == ""
    assert output["interrupted"] is False
    assert output["isImage"] is False
    assert output["stdout"] != TEXT
    assert original["tool_response"]["stdout"] == TEXT
    artifact_id = next(tmp_path.rglob("*.txt")).stem
    assert store.get("test", artifact_id) == TEXT
    assert artifact_id in output["stdout"]


def test_fail_closed_for_other_events_and_sensitive_results(tmp_path):
    store = ArtifactStore(tmp_path)
    cases = [
        event(tool_name="Read"),
        event(hook_event_name="PostToolUseFailure"),
        event(tool_response={**event()["tool_response"], "stderr": "warning"}),
        event(tool_response={**event()["tool_response"], "interrupted": True}),
        event(tool_response={**event()["tool_response"], "exitCode": 1}),
        event(tool_response={**event()["tool_response"], "stdout": "permission denied\n" + TEXT}),
        event(tool_response="unrecognized"),
    ]
    for item in cases:
        assert post_tool_use(item, policy=POLICY, store=store, project_id="test", recovery_available=True) is None
    assert list(tmp_path.rglob("*.txt")) == []


def test_requires_approved_safe_policy(tmp_path):
    store = ArtifactStore(tmp_path)
    for policy in ({**POLICY, "approved": False}, {**POLICY, "mode": "observe"}):
        assert post_tool_use(event(), policy=policy, store=store, project_id="test", recovery_available=True) is None
    assert list(tmp_path.rglob("*.txt")) == []


def test_recovery_capability_defaults_to_pass_through(tmp_path):
    store = ArtifactStore(tmp_path)
    assert post_tool_use(event(), policy=POLICY, store=store, project_id="test") is None
    assert list(tmp_path.rglob("*.txt")) == []
