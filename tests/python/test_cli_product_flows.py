"""CLI acceptance paths for explicitly managed local product features."""

import json
import os
from pathlib import Path
import subprocess
import sys

from julius.evaluation_runner import FrozenFixture
from julius.cli import _integration_state_root


def _cli(tmp_path: Path, *args: str, success: bool = True) -> object:
    process = subprocess.run(
        [sys.executable, "-m", "julius", *args, "--data-dir", str(tmp_path / "data")],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
    )
    assert (process.returncode == 0) is success, process.stderr
    return json.loads(process.stdout) if process.stdout else process.stderr


def test_cli_claude_setup_preview_apply_and_restore(tmp_path: Path) -> None:
    project = tmp_path / "project"
    claude = project / ".claude"
    claude.mkdir(parents=True)
    settings = claude / "settings.json"
    mcp = project / ".mcp.json"
    original_settings = b'{"permissions":{"allow":["Read"]}}\n'
    original_mcp = b'{"mcpServers":{"other":{"command":"true"}}}\n'
    settings.write_bytes(original_settings)
    mcp.write_bytes(original_mcp)
    args = ("setup", "--project-root", str(project), "--project", "fixture-project")
    preview = _cli(tmp_path, *args)
    assert isinstance(preview, dict)
    assert preview["applied"] is False
    assert "julius-recovery" in preview["mcpDiff"]
    assert settings.read_bytes() == original_settings
    assert mcp.read_bytes() == original_mcp
    _cli(tmp_path, *args, "--apply-plan", "wrong", success=False)
    applied = _cli(tmp_path, *args, "--apply-plan", preview["planHash"])
    assert isinstance(applied, dict) and applied["applied"] is True
    repeated = _cli(tmp_path, *args, "--apply-plan", preview["planHash"])
    assert isinstance(repeated, dict) and repeated["applied"] is False
    assert b"julius" in settings.read_bytes()
    assert b"julius-recovery" in mcp.read_bytes()
    alias = tmp_path / "project-alias"
    alias.symlink_to(project, target_is_directory=True)
    removed = _cli(tmp_path, "integrations", "remove", "claude", "--project-root", str(alias))
    assert removed == {"removed": True, "integration": "claude"}
    assert settings.read_bytes() == original_settings
    assert mcp.read_bytes() == original_mcp


def test_default_project_local_data_keeps_config_backups_outside_project(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    project = tmp_path / "project"
    project.mkdir()
    state = _integration_state_root(project / ".julius", project)
    assert state.is_relative_to(tmp_path / "state")
    assert not state.is_relative_to(project)


def test_cli_model_snapshot_history_keeps_unknown(tmp_path: Path) -> None:
    snapshot = {
        "endpoint": "http://127.0.0.1:11434", "provider": "ollama",
        "requested_model": "fixture", "state": "unknown", "source": "fixture",
    }
    source = tmp_path / "model.json"
    source.write_text(json.dumps(snapshot))
    recorded = _cli(tmp_path, "models", "record", "--state-file", str(source))
    assert isinstance(recorded, dict) and recorded["state"] == "unknown"
    history = _cli(tmp_path, "models", "history", "--endpoint", snapshot["endpoint"],
                   "--model", "fixture")
    assert isinstance(history, list) and len(history) == 1
    assert history[0]["snapshotId"] == recorded["snapshotId"]
    assert history[0]["tokenizer"] is None


def test_cli_offline_fixture_replay_preserves_signed_output_difference(tmp_path: Path) -> None:
    snapshot = {"repo": "frozen"}
    fixture_id = FrozenFixture.digest("task", snapshot)
    payload = {
        "fixtures": [{"task_id": "task", "fixture_id": fixture_id, "snapshot": snapshot}],
        "attempts": [
            {"fixture_id": fixture_id, "arm_id": "baseline", "attempt_index": 0,
             "success": True, "input_tokens": 100, "output_tokens": 20,
             "cache_read_tokens": 0, "cache_write_tokens": 0,
             "auxiliary_tokens": 0, "cost_usd": 1.0, "latency_ms": 100.0},
            {"fixture_id": fixture_id, "arm_id": "candidate", "attempt_index": 0,
             "success": True, "input_tokens": 80, "output_tokens": 30,
             "cache_read_tokens": 0, "cache_write_tokens": 0,
             "auxiliary_tokens": 0, "cost_usd": 0.8, "latency_ms": 90.0},
        ],
        "baselineArm": "baseline", "candidateArm": "candidate",
    }
    source = tmp_path / "replay.json"
    source.write_text(json.dumps(payload))
    result = _cli(tmp_path, "evaluate", "replay", "--state-file", str(source))
    assert isinstance(result, dict)
    assert result["scope"] == "offline_fixture_replay"
    assert result["analysis"]["savings"]["input_tokens"] == 20
    assert result["analysis"]["savings"]["output_tokens"] == -10
