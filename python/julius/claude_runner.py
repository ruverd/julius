"""Ephemeral Claude Code session configuration for opt-in Julius recovery."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ClaudeLaunchPlan:
    """Data to write into temporary files before starting Claude Code."""

    settings: dict[str, Any]
    mcp_config: dict[str, Any]
    claude_command: tuple[str, ...]


def build_launch_plan(
    *,
    project_id: str,
    data_dir: Path,
    settings_path: Path,
    mcp_path: Path,
    python_executable: str = sys.executable,
    claude_executable: str = "claude",
    claude_args: Sequence[str] = (),
    enable_safe_hook: bool = False,
) -> ClaudeLaunchPlan:
    """Build session-only config without inspecting or changing Claude credentials."""
    if not project_id or not project_id.strip():
        raise ValueError("A non-empty project ID is required")
    if not python_executable or not claude_executable:
        raise ValueError("Executable names must be non-empty")
    root = str(data_dir.expanduser().resolve())
    julius_args = [python_executable, "-m", "julius"]
    scope_args = ["--project", project_id, "--data-dir", root]
    hook_command = shlex.join([
        *julius_args, "hook", "claude-post-tool-use", *scope_args,
        "--profile", "safe", "--recovery-available",
    ])
    return ClaudeLaunchPlan(
        settings={"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": hook_command},
        ]}]}} if enable_safe_hook else {},
        mcp_config={"mcpServers": {"julius-recovery": {
            "type": "stdio", "command": python_executable,
            "args": ["-m", "julius", "mcp", "recovery", *scope_args],
        }}},
        claude_command=(
            claude_executable, "--settings", str(settings_path),
            "--mcp-config", str(mcp_path), *claude_args,
        ),
    )


def run_claude(
    *,
    project_id: str,
    data_dir: Path,
    claude_args: Sequence[str] = (),
    python_executable: str = sys.executable,
    claude_executable: str = "claude",
    runner: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
    enable_safe_hook: bool = False,
    recovery_verified: bool = False,
) -> int:
    """Launch Claude once; remove only Julius's temporary config on exit."""
    if enable_safe_hook and not recovery_verified:
        raise ValueError("Safe hook requires verified model-accessible recovery")
    with tempfile.TemporaryDirectory(prefix="julius-claude-") as directory:
        settings_path = Path(directory) / "settings.json"
        mcp_path = Path(directory) / "mcp.json"
        plan = build_launch_plan(
            project_id=project_id, data_dir=data_dir,
            settings_path=settings_path, mcp_path=mcp_path,
            python_executable=python_executable,
            claude_executable=claude_executable, claude_args=claude_args,
            enable_safe_hook=enable_safe_hook,
        )
        settings_path.write_text(json.dumps(plan.settings), encoding="utf-8")
        mcp_path.write_text(json.dumps(plan.mcp_config), encoding="utf-8")
        return runner(list(plan.claude_command), check=False).returncode
