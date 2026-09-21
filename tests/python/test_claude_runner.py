import json
import shlex
import subprocess
from pathlib import Path

import pytest

from julius.claude_runner import build_launch_plan, run_claude


def test_plan_scopes_recovery_and_preserves_default_claude_configuration(tmp_path):
    plan = build_launch_plan(
        project_id="project with spaces", data_dir=tmp_path / "artifacts",
        settings_path=tmp_path / "settings.json", mcp_path=tmp_path / "mcp.json",
        python_executable="/path with spaces/python", claude_args=("--model", "sonnet"),
        enable_safe_hook=True,
    )
    assert plan.claude_command == (
        "claude", "--settings", str(tmp_path / "settings.json"),
        "--mcp-config", str(tmp_path / "mcp.json"), "--model", "sonnet",
    )
    assert "--strict-mcp-config" not in plan.claude_command
    assert "--permission-mode" not in plan.claude_command
    hook = plan.settings["hooks"]["PostToolUse"][0]
    assert hook["matcher"] == "Bash"
    assert shlex.split(hook["hooks"][0]["command"]) == [
        "/path with spaces/python", "-m", "julius", "hook", "claude-post-tool-use",
        "--project", "project with spaces", "--data-dir", str((tmp_path / "artifacts").resolve()),
        "--profile", "safe", "--recovery-available",
    ]
    server = plan.mcp_config["mcpServers"]["julius-recovery"]
    assert server["args"] == [
        "-m", "julius", "mcp", "recovery", "--project", "project with spaces",
        "--data-dir", str((tmp_path / "artifacts").resolve()),
    ]


def test_run_uses_ephemeral_files_and_propagates_status(tmp_path):
    seen = {}

    def fake_run(argv, *, check):
        assert check is False
        seen["argv"] = argv
        seen["settings"] = json.loads(Path(argv[2]).read_text())
        seen["mcp"] = json.loads(Path(argv[4]).read_text())
        return subprocess.CompletedProcess(argv, 17)

    assert run_claude(project_id="p", data_dir=tmp_path, runner=fake_run) == 17
    assert not Path(seen["argv"][2]).exists()
    assert not Path(seen["argv"][4]).exists()
    assert seen["settings"] == {}
    assert seen["mcp"]["mcpServers"]["julius-recovery"]
    assert list(tmp_path.iterdir()) == []


def test_safe_hook_requires_verified_recovery(tmp_path):
    with pytest.raises(ValueError, match="verified model-accessible recovery"):
        run_claude(project_id="p", data_dir=tmp_path, enable_safe_hook=True,
                   runner=lambda *a, **k: None)


def test_rejects_blank_project_before_launch(tmp_path):
    with pytest.raises(ValueError, match="project ID"):
        run_claude(project_id=" ", data_dir=tmp_path, runner=lambda *a, **k: None)
