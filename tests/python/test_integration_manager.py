"""Integration management tests only touch temporary project directories."""

import json

import pytest

from julius.integration_manager import ClaudeIntegrationManager


def manager(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / ".claude").mkdir()
    return ClaudeIntegrationManager(project, tmp_path / "state"), project


def preview(managed):
    return managed.preview(
        hook_command="julius hook claude-post-tool-use --project p --profile safe",
        mcp_command="julius", mcp_args=["mcp", "recovery", "--project", "p"],
    )


def test_preview_apply_remove_preserves_existing_bytes(tmp_path):
    managed, project = manager(tmp_path)
    settings = project / ".claude" / "settings.json"
    mcp = project / ".mcp.json"
    old_settings = b'{"permissions":{"deny":["Bash(rm *)"]}}\n'
    old_mcp = b'{"mcpServers":{"other":{"command":"other"}}}\n'
    settings.write_bytes(old_settings)
    mcp.write_bytes(old_mcp)
    planned = preview(managed)
    assert "julius" in planned.settings.diff
    assert "julius-recovery" in planned.mcp.diff
    assert settings.read_bytes() == old_settings
    assert mcp.read_bytes() == old_mcp
    assert managed.apply(planned)
    assert not managed.apply(planned)
    repeat = preview(managed)
    assert repeat.settings.diff == ""
    assert repeat.mcp.diff == ""
    assert not managed.apply(repeat)
    assert json.loads(settings.read_bytes())["permissions"]["deny"] == ["Bash(rm *)"]
    assert json.loads(mcp.read_bytes())["mcpServers"]["other"] == {"command": "other"}
    assert managed.remove()
    assert not managed.remove()
    assert settings.read_bytes() == old_settings
    assert mcp.read_bytes() == old_mcp


def test_created_files_are_removed_and_drift_is_refused(tmp_path):
    managed, project = manager(tmp_path)
    planned = preview(managed)
    managed.apply(planned)
    settings = project / ".claude" / "settings.json"
    settings.write_text("user edit")
    with pytest.raises(ValueError, match="changed"):
        managed.remove()
    assert (project / ".mcp.json").exists()
    settings.write_bytes(planned.settings.desired)
    assert managed.remove()
    assert not settings.exists()
    assert not (project / ".mcp.json").exists()


def test_recovery_claim_requires_verification(tmp_path):
    managed, _ = manager(tmp_path)
    with pytest.raises(ValueError, match="verified"):
        managed.preview(
            hook_command="julius hook claude-post-tool-use --recovery-available",
            mcp_command="julius", mcp_args=[],
        )


def test_apply_rejects_change_between_preview_and_apply(tmp_path):
    managed, project = manager(tmp_path)
    planned = preview(managed)
    (project / ".mcp.json").write_text('{"mcpServers":{"user":{"command":"x"}}}')
    with pytest.raises(ValueError, match="changed"):
        managed.apply(planned)
    assert not (project / ".claude" / "settings.json").exists()


def test_preview_rejects_symlink_without_reading_external_file(tmp_path):
    managed, project = manager(tmp_path)
    outside = tmp_path / "secret"
    outside.write_text("private content")
    (project / ".claude" / "settings.json").symlink_to(outside)
    with pytest.raises((ValueError, OSError)):
        preview(managed)
    assert outside.read_text() == "private content"


def test_partial_managed_state_is_refused_before_more_writes(tmp_path):
    managed, project = manager(tmp_path)
    planned = preview(managed)
    managed.managed.apply(planned.settings)
    with pytest.raises(ValueError, match="Incomplete"):
        managed.apply(planned)
    with pytest.raises(ValueError, match="Incomplete"):
        preview(managed)
    assert not (project / ".mcp.json").exists()


def test_repeat_preview_refuses_changed_commands_or_drift(tmp_path):
    managed, project = manager(tmp_path)
    planned = preview(managed)
    managed.apply(planned)
    with pytest.raises(ValueError, match="changed"):
        managed.preview(
            hook_command="different hook", mcp_command="julius",
            mcp_args=["mcp", "recovery", "--project", "p"],
        )
    (project / ".mcp.json").write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        preview(managed)
