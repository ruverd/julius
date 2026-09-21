"""Codex integration tests use disposable project directories."""

import json

import pytest

from julius.codex_integration_manager import CodexIntegrationManager


COMMAND = "julius hook codex-user-prompt-submit --project example"


def manager(tmp_path):
    project = tmp_path / "project"
    (project / ".codex").mkdir(parents=True)
    return CodexIntegrationManager(project, tmp_path / "state"), project


def test_preview_apply_remove_preserves_existing_hooks(tmp_path):
    managed, project = manager(tmp_path)
    target = project / ".codex" / "hooks.json"
    original = b'{"other":true,"hooks":{"UserPromptSubmit":[{"hooks":[{"type":"command","command":"other"}]}]}}\n'
    target.write_bytes(original)
    plan = managed.preview(hook_command=COMMAND)
    assert target.read_bytes() == original
    assert "+" in plan.hooks.diff
    assert managed.apply(plan)
    assert not managed.apply(plan)
    value = json.loads(target.read_bytes())
    assert value["other"] is True
    assert value["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"] == "other"
    assert value["hooks"]["UserPromptSubmit"][1] == plan.entry.hook_entry
    assert "matcher" not in plan.entry.hook_entry
    repeat = managed.preview(hook_command=COMMAND)
    assert repeat.hooks.diff == ""
    assert not managed.apply(repeat)
    assert managed.remove()
    assert not managed.remove()
    assert target.read_bytes() == original


def test_created_file_removed_and_drift_refused(tmp_path):
    managed, project = manager(tmp_path)
    target = project / ".codex" / "hooks.json"
    plan = managed.preview(hook_command=COMMAND)
    managed.apply(plan)
    target.write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        managed.remove()
    target.write_bytes(plan.hooks.desired)
    assert managed.remove()
    assert not target.exists()


@pytest.mark.parametrize("raw", [b"[1]", b"{", b'{"hooks":[]}', b'{"hooks":{"UserPromptSubmit":{}}}', b'{"hooks":{"UserPromptSubmit":[{}]}}', b" " * 1_048_577])
def test_invalid_config_is_refused(tmp_path, raw):
    managed, project = manager(tmp_path)
    (project / ".codex" / "hooks.json").write_bytes(raw)
    with pytest.raises(ValueError):
        managed.preview(hook_command=COMMAND)


def test_julius_collision_and_changed_command_refused(tmp_path):
    managed, project = manager(tmp_path)
    target = project / ".codex" / "hooks.json"
    target.write_text(json.dumps({"hooks": {"OtherEvent": [{"hooks": [{"command": "julius custom"}]}]}}))
    with pytest.raises(ValueError, match="Julius"):
        managed.preview(hook_command=COMMAND)
    target.unlink()
    plan = managed.preview(hook_command=COMMAND)
    managed.apply(plan)
    with pytest.raises(ValueError, match="command changed"):
        managed.preview(hook_command="julius hook another")


def test_change_after_preview_and_symlink_refused(tmp_path):
    managed, project = manager(tmp_path)
    target = project / ".codex" / "hooks.json"
    plan = managed.preview(hook_command=COMMAND)
    target.write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        managed.apply(plan)
    target.unlink()
    outside = tmp_path / "outside"
    outside.write_text("secret")
    target.symlink_to(outside)
    with pytest.raises((ValueError, OSError)):
        managed.preview(hook_command=COMMAND)


def test_requires_existing_codex_directory(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(ValueError, match=".codex"):
        CodexIntegrationManager(project, tmp_path / "state")
