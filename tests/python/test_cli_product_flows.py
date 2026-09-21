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


def test_cli_codex_setup_preview_apply_and_restore(tmp_path: Path) -> None:
    project = tmp_path / "project"
    codex = project / ".codex"
    codex.mkdir(parents=True)
    hooks = codex / "hooks.json"
    original = b'{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"true"}]}]}}\n'
    hooks.write_bytes(original)
    args = ("setup", "--integration", "codex", "--project-root", str(project))
    preview = _cli(tmp_path, *args)
    assert isinstance(preview, dict)
    assert preview["integration"] == "codex"
    assert preview["trustRequired"] is True
    assert preview["applied"] is False
    assert "codex-user-prompt-submit" in preview["hooksDiff"]
    assert hooks.read_bytes() == original
    _cli(tmp_path, *args, "--apply-plan", "wrong", success=False)
    applied = _cli(tmp_path, *args, "--apply-plan", preview["planHash"])
    assert isinstance(applied, dict) and applied["applied"] is True
    repeated = _cli(tmp_path, *args, "--apply-plan", preview["planHash"])
    assert isinstance(repeated, dict) and repeated["applied"] is False
    installed = json.loads(hooks.read_bytes())
    assert installed["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "true"
    assert "UserPromptSubmit" in installed["hooks"]
    removed = _cli(tmp_path, "integrations", "remove", "codex", "--project-root", str(project))
    assert removed == {"removed": True, "integration": "codex"}
    assert hooks.read_bytes() == original


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
    refused = _cli(tmp_path, "models", "scan", "--endpoint", "http://bad-host:1111")
    assert isinstance(refused, dict)
    assert refused["snapshots"] == []
    assert refused["error"] is not None


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


def test_cli_policy_check_suspends_negative_net_without_model_call(tmp_path: Path) -> None:
    scope = {
        "project_id": "p", "model_id": "m", "strategy_id": "repeated-lines",
        "strategy_version": "1",
    }
    policy = {
        "version": "1", "minimum_samples": 1,
        "max_error_rate": 1.0, "max_recovery_rate": 1.0,
        "max_rework_rate": 1.0, "max_mean_latency_ms": 1000.0,
        "min_total_net_savings_usd": 0.0,
    }
    payload = {
        "scope": scope, "policy": policy,
        "outcomes": [{
            "scope": scope, "sequence": 0, "task_id": "task-1", "error": False,
            "recovery_used": False, "rework_needed": False,
            "latency_ms": 50.0, "net_savings_usd": -0.01,
        }],
    }
    source = tmp_path / "guard.json"
    source.write_text(json.dumps(payload))
    decision = _cli(tmp_path, "policy", "check", "--state-file", str(source))
    assert isinstance(decision, dict)
    assert decision["status"] == "suspended"
    assert decision["reasons"] == ["below_min_total_net_savings_usd"]


def test_cli_persistent_quality_guard_blocks_later_optimization(tmp_path: Path) -> None:
    scope = {
        "project_id": "p", "model_id": "m", "strategy_id": "repeated-lines",
        "strategy_version": "1",
    }
    policy = {
        "version": "1", "minimum_samples": 1,
        "max_error_rate": 1.0, "max_recovery_rate": 1.0,
        "max_rework_rate": 1.0, "max_mean_latency_ms": 1000.0,
        "min_total_net_savings_usd": 0.0,
    }
    config = tmp_path / "guard.json"
    config.write_text(json.dumps({"scope": scope, "policy": policy}))
    content = tmp_path / "content.txt"
    content.write_text(("neutral repeated content " + "x" * 160 + "\n") * 8)

    def record(sequence: int, task: str, net: float) -> dict:
        payload = {"scope": scope, "policy": policy, "recordType": "outcome", "record": {
            "scope": scope, "sequence": sequence, "task_id": task,
            "error": False, "recovery_used": False, "rework_needed": False,
            "latency_ms": 10.0, "net_savings_usd": net,
        }}
        source = tmp_path / f"record-{sequence}.json"
        source.write_text(json.dumps(payload))
        result = _cli(tmp_path, "policy", "record", "--state-file", str(source))
        assert isinstance(result, dict)
        return result

    assert record(0, "task-1", 0.01)["status"] == "enabled"
    first = _cli(tmp_path, "optimize", str(content), "--project", "p", "--model", "m", "--profile", "safe",
                 "--guard-file", str(config))
    assert isinstance(first, dict) and first["receipt"]["applied"] is True
    assert record(1, "task-2", -0.02)["status"] == "suspended"
    status = _cli(tmp_path, "policy", "status", "--state-file", str(config))
    assert isinstance(status, dict) and status["status"] == "suspended"
    blocked = _cli(tmp_path, "optimize", str(content), "--project", "p", "--model", "m", "--profile", "safe",
                   "--guard-file", str(config), success=False)
    assert "Quality guard blocked optimization: suspended" in blocked
