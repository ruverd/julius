"""Claude project configuration planning uses only in-memory JSON fixtures."""

import json

import pytest

from julius.claude_config import plan_claude_project_config, unmerge_claude_project_config


ARGS = ["mcp", "recovery", "--project", "example", "--data-dir", "/tmp/julius"]


def plan(settings=None, mcp=None):
    return plan_claude_project_config(
        settings, mcp,
        hook_command="/usr/local/bin/julius hook claude-post-tool-use --project example --profile safe --recovery-available",
        mcp_command="/usr/local/bin/julius", mcp_args=ARGS,
    )


def test_merge_and_unmerge_preserve_unrelated_configuration():
    original_settings = {"permissions": {"deny": ["Bash(rm *)"]}, "hooks": {
        "PostToolUse": [{"matcher": "Write", "hooks": [{"type": "command", "command": "echo wrote"}]}],
        "SessionStart": [{"hooks": [{"type": "command", "command": "echo ready"}]}],
    }}
    original_mcp = {"mcpServers": {"other": {"command": "other-server"}}, "metadata": {"x": 1}}
    result = plan(json.dumps(original_settings).encode(), json.dumps(original_mcp).encode())
    merged_settings = json.loads(result.settings)
    merged_mcp = json.loads(result.mcp)
    assert merged_settings["permissions"] == original_settings["permissions"]
    assert merged_settings["hooks"]["PostToolUse"][0] == original_settings["hooks"]["PostToolUse"][0]
    assert merged_settings["hooks"]["SessionStart"] == original_settings["hooks"]["SessionStart"]
    assert merged_mcp["mcpServers"]["other"] == original_mcp["mcpServers"]["other"]
    assert merged_mcp["mcpServers"]["julius-recovery"]["args"] == ARGS
    restored_settings, restored_mcp = unmerge_claude_project_config(result.settings, result.mcp, result)
    assert json.loads(restored_settings) == original_settings
    assert json.loads(restored_mcp) == original_mcp


def test_unmerge_preserves_unrelated_later_edits():
    result = plan()
    settings = json.loads(result.settings)
    mcp = json.loads(result.mcp)
    settings["permissions"] = {"ask": ["Bash(git push *)"]}
    mcp["mcpServers"]["other"] = {"command": "other"}
    restored_settings, restored_mcp = unmerge_claude_project_config(
        json.dumps(settings).encode(), json.dumps(mcp).encode(), result,
    )
    assert json.loads(restored_settings) == {"permissions": settings["permissions"]}
    assert json.loads(restored_mcp) == {"mcpServers": {"other": {"command": "other"}}}


def test_refuses_existing_name_hook_and_drift():
    result = plan()
    with pytest.raises(ValueError, match="already exists"):
        plan(None, result.mcp)
    with pytest.raises(ValueError, match="Existing Julius hook"):
        plan(result.settings, None)
    settings = json.loads(result.settings)
    settings["hooks"]["PostToolUse"][0]["hooks"][0]["command"] = "changed"
    with pytest.raises(ValueError, match="changed"):
        unmerge_claude_project_config(json.dumps(settings).encode(), result.mcp, result)
    mcp = json.loads(result.mcp)
    mcp["mcpServers"]["julius-recovery"]["args"].append("changed")
    with pytest.raises(ValueError, match="changed"):
        unmerge_claude_project_config(result.settings, json.dumps(mcp).encode(), result)


def test_rejects_malformed_existing_structures():
    for settings, mcp in ((b"[]", None), (b'{"hooks":[]}', None),
                          (b'{"hooks":{"PostToolUse":{}}}', None),
                          (None, b'{"mcpServers":[]}')):
        with pytest.raises(ValueError):
            plan(settings, mcp)
