"""Opt-in, bounded synthetic Claude Code baseline/safe-hook pair."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .artifacts import ArtifactStore
from .claude_print_runner import parse_stream_json
from .claude_runner import build_launch_plan


_LINE = "JULIUS PAIR FIXTURE alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha alpha\n"
FIXED_COMMAND = (
    "printf 'JULIUS PAIR FIXTURE alpha alpha alpha alpha alpha alpha alpha alpha "
    "alpha alpha alpha alpha\\n%.0s' {1..96}"
)
EXPECTED_OUTPUT = _LINE * 96
EXPECTED_ANSWER = "96"
PROMPT = (
    "Run this exact Bash command once, then count the lines in its output. "
    "Answer with only the decimal line count. Do not run another command.\n"
    f"{FIXED_COMMAND}"
)
_RECOVERY_TOOL = "mcp__julius-recovery__restore_artifact"
_ARTIFACT_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
_MAX_STREAM_BYTES = 10_000_000


def gate_hook_event(event: Any, *, once_file: Path | None = None) -> dict[str, Any] | None:
    """Deny any tool request except the one fixed command and project recovery."""
    allowed = False
    if isinstance(event, dict):
        name = event.get("tool_name")
        inputs = event.get("tool_input")
        if isinstance(inputs, dict):
            if name == "Bash":
                allowed = (
                    inputs.get("command") == FIXED_COMMAND
                    and set(inputs) <= {"command", "description", "timeout"}
                    and ("description" not in inputs or isinstance(inputs["description"], str))
                    and ("timeout" not in inputs or type(inputs["timeout"]) is int)
                )
            elif name == _RECOVERY_TOOL:
                allowed = (
                    set(inputs) == {"artifactId"}
                    and isinstance(inputs["artifactId"], str)
                    and _ARTIFACT_ID.fullmatch(inputs["artifactId"]) is not None
                )
            elif name == "EndConversation":
                # Claude Code keeps this completion tool while other tools remain.
                allowed = True
    if allowed and once_file is not None and event["tool_name"] == "Bash":
        try:
            descriptor = os.open(
                once_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except OSError:
            allowed = False
        else:
            os.close(descriptor)
    if allowed:
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "Synthetic pair permits only its fixed printf and Julius recovery.",
    }}


def _stream_evidence(stdout: str) -> dict[str, Any]:
    requests: list[tuple[str | None, str, dict[str, Any]]] = []
    results: set[str] = set()
    unexpected = 0
    recovery_requests = 0
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        message = event.get("message")
        blocks = message.get("content") if isinstance(message, dict) else None
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                name = block.get("name")
                inputs = block.get("input")
                ident = block.get("id")
                if not isinstance(name, str) or not isinstance(inputs, dict):
                    unexpected += 1
                    continue
                requests.append((ident if isinstance(ident, str) else None, name, inputs))
                if name == _RECOVERY_TOOL:
                    recovery_requests += 1
                if gate_hook_event({"tool_name": name, "tool_input": inputs}) is not None:
                    unexpected += 1
            elif block.get("type") == "tool_result":
                ident = block.get("tool_use_id")
                if isinstance(ident, str) and block.get("is_error") is not True:
                    results.add(ident)
    bash_ids = [ident for ident, name, inputs in requests
                if name == "Bash" and inputs.get("command") == FIXED_COMMAND]
    return {
        "bash_requests": len(bash_ids),
        "bash_results": sum(ident is not None and ident in results for ident in bash_ids),
        "recovery_requests": recovery_requests,
        "unexpected_tool_requests": unexpected,
    }


def _artifact_evidence(data_dir: Path, project_id: str, stdout: str) -> list[dict[str, Any]]:
    root = data_dir / "artifacts"
    if not root.exists():
        return []
    directory = root / hashlib.sha256(project_id.encode()).hexdigest()
    if not directory.exists() or directory.is_symlink():
        return []
    store = ArtifactStore(root)
    evidence = []
    for metadata_path in sorted(directory.glob("*.json")):
        ident = metadata_path.stem
        try:
            original = store.get(project_id, ident)
        except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
            match = False
        else:
            match = original == EXPECTED_OUTPUT
        evidence.append({
            "artifact_id": ident,
            "original_matches_fixed_output": match,
            "id_observed_in_stream": ident in stdout,
        })
    return evidence


def _text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _arm(
    *, name: str, run_dir: Path, project_id: str, max_turns: int,
    max_budget_usd: float, timeout_seconds: float, model: str | None,
    python_executable: str, claude_executable: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> dict[str, Any]:
    arm_dir = run_dir / name
    arm_dir.mkdir(mode=0o700)
    project_dir = arm_dir / "project"
    project_dir.mkdir(mode=0o700)
    data_dir = arm_dir / "julius-data"
    data_dir.mkdir(mode=0o700)
    settings_path = arm_dir / "settings.json"
    mcp_path = arm_dir / "mcp.json"
    arm_project = f"{project_id}-{run_dir.name}-{name}"
    plan = build_launch_plan(
        project_id=arm_project, data_dir=data_dir,
        settings_path=settings_path, mcp_path=mcp_path,
        python_executable=python_executable, claude_executable=claude_executable,
        task_id="synthetic-pair", enable_safe_hook=name == "safe_hook",
        claude_args=(
            "--print", "--output-format", "stream-json", "--verbose",
            "--include-hook-events", "--no-session-persistence", "--restricted",
            "--strict-mcp-config", "--permission-mode", "dontAsk",
            "--permission-prompts", "none", "--tools", "Bash",
            "--allowedTools", f"Bash({FIXED_COMMAND})", _RECOVERY_TOOL,
            "--max-turns", str(max_turns), "--max-budget-usd", str(max_budget_usd),
            *(["--model", model] if model is not None else []),
        ),
    )
    settings = plan.settings
    settings.setdefault("hooks", {})["PreToolUse"] = [{
        "matcher": "*", "hooks": [{"type": "command", "command": shlex.join([
            python_executable, "-m", "julius.claude_pair", "--gate",
            str(arm_dir / "fixed-command-used"),
        ])}],
    }]
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    mcp_path.write_text(json.dumps(plan.mcp_config), encoding="utf-8")
    environment = os.environ.copy()
    package_root = str(Path(__file__).resolve().parent.parent)
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, [
        package_root, environment.get("PYTHONPATH", ""),
    ]))
    started = time.monotonic()
    stdout = ""
    stderr = ""
    exit_code = -1
    failure: str | None = None
    try:
        completed = runner(
            list(plan.claude_command), input=PROMPT, text=True, capture_output=True,
            timeout=timeout_seconds, check=False, cwd=project_dir, env=environment,
        )
        stdout = _text(completed.stdout)
        stderr = _text(completed.stderr)
        exit_code = completed.returncode
    except subprocess.TimeoutExpired as error:
        failure = "timeout"
        stdout = _text(error.stdout)
        stderr = _text(error.stderr)
    except OSError as error:
        failure = f"launch_error:{type(error).__name__}"
        stderr = str(error)
    latency = time.monotonic() - started
    stdout_path = arm_dir / "stdout.jsonl"
    stderr_path = arm_dir / "stderr.txt"
    stdout_path.write_text(stdout[:_MAX_STREAM_BYTES], encoding="utf-8")
    stderr_path.write_text(stderr[:_MAX_STREAM_BYTES], encoding="utf-8")
    try:
        parsed = parse_stream_json(stdout, exit_code=exit_code)
    except ValueError:
        parsed = parse_stream_json("", exit_code=exit_code)
        failure = failure or "oversized_stream"
    evidence = _stream_evidence(stdout)
    artifacts = _artifact_evidence(data_dir, arm_project, stdout)
    passed = bool(
        parsed["complete"] and parsed["output"] == EXPECTED_ANSWER
        and evidence["bash_requests"] == 1 and evidence["bash_results"] == 1
        and evidence["unexpected_tool_requests"] == 0
    )
    result = {
        "arm": name, "project_id": arm_project,
        "complete": parsed["complete"], "passed": passed,
        "error": failure or parsed["error"], "exit_code": exit_code,
        "session_id": parsed["session_id"],
        "actual_model": parsed["actual_model"],
        "observed_models": parsed["observed_models"],
        "usage": parsed["usage"], "cost_usd": parsed["cost_usd"],
        "cost_scope": parsed["cost_scope"],
        "latency_seconds": latency, "answer": parsed["output"],
        **evidence, "artifacts": artifacts,
        "stdout_path": str(stdout_path), "stderr_path": str(stderr_path),
    }
    (arm_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def run_claude_pair(
    *, work_dir: Path, project_id: str, max_turns: int,
    max_budget_usd: float, timeout_seconds: float, model: str | None = None,
    python_executable: str = sys.executable, claude_executable: str = "claude",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Run two explicit client sessions and retain each attempt in a unique directory."""
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("project_id must be non-empty")
    if type(max_turns) is not int or not 1 <= max_turns <= 100:
        raise ValueError("max_turns must be between 1 and 100")
    if (type(max_budget_usd) not in (int, float) or not math.isfinite(max_budget_usd)
            or max_budget_usd <= 0):
        raise ValueError("max_budget_usd must be positive and finite")
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0):
        raise ValueError("timeout_seconds must be positive and finite")
    if model is not None and (not isinstance(model, str) or not model.strip() or "\x00" in model):
        raise ValueError("model must be a non-empty name")
    root = Path(work_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_dir = root / f"claude-pair-{uuid.uuid4()}"
    run_dir.mkdir(mode=0o700)
    arms = []
    for name in ("baseline", "safe_hook"):
        arms.append(_arm(
            name=name, run_dir=run_dir, project_id=project_id,
            max_turns=max_turns, max_budget_usd=max_budget_usd,
            timeout_seconds=timeout_seconds, model=model,
            python_executable=python_executable, claude_executable=claude_executable,
            runner=runner,
        ))
    report = {
        "run_dir": str(run_dir), "task_id": "synthetic-pair",
        "command_sha256": hashlib.sha256(FIXED_COMMAND.encode()).hexdigest(),
        "expected_answer": EXPECTED_ANSWER,
        "limits_per_arm": {"max_turns": max_turns, "max_budget_usd": max_budget_usd,
                           "timeout_seconds": timeout_seconds},
        "arms": arms,
        "same_observed_model": (
            arms[0]["actual_model"] is not None
            and arms[0]["actual_model"] == arms[1]["actual_model"]
        ),
        "conclusion": "descriptive_pair_only",
    }
    (run_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "--gate":
        raise SystemExit("usage: python -m julius.claude_pair --gate ONCE_FILE")
    raw = sys.stdin.buffer.read(65537)
    try:
        event = json.loads(raw) if len(raw) <= 65536 else None
    except (UnicodeError, json.JSONDecodeError):
        event = None
    decision = gate_hook_event(event, once_file=Path(sys.argv[2]))
    if decision is not None:
        print(json.dumps(decision))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
