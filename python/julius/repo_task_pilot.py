"""Exploratory, opt-in paired Claude Code runs over a frozen tiny repository."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shlex
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .claude_pair import _stream_evidence, gate_hook_event
from .claude_print_runner import parse_stream_json
from .claude_runner import build_launch_plan

CORPUS_PATH = Path(__file__).resolve().parent / "data/repo_task_pilot.json"
MAX_STREAM_BYTES = 10_000_000


def _corpus(path: Path) -> tuple[bytes, dict[str, Any]]:
    raw = path.read_bytes()
    data = json.loads(raw)
    files, tasks = data["files"], data["tasks"]
    if not isinstance(files, dict) or not isinstance(tasks, list):
        raise ValueError("Invalid frozen corpus")
    if set(files) != {"README.md", "notes.py", "store.py", "routes.py"}:
        raise ValueError("Unexpected corpus files")
    if any(not isinstance(content, str) for content in files.values()):
        raise ValueError("Invalid corpus content")
    if len(tasks) != 4 or len({task["id"] for task in tasks}) != 4:
        raise ValueError("Invalid frozen tasks")
    return raw, data


def _as_text(value: str | bytes | None) -> str:
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value or ""


def _arm(*, run_dir: Path, task: dict[str, str], files: dict[str, str], name: str,
         project_id: str, max_turns: int, max_budget_usd: float, timeout_seconds: float,
         model: str | None, python_executable: str, claude_executable: str,
         runner: Callable[..., subprocess.CompletedProcess[str]]) -> dict[str, Any]:
    arm_dir = run_dir / task["id"] / name
    arm_dir.mkdir(parents=True, mode=0o700)
    project_dir = arm_dir / "project"
    project_dir.mkdir(mode=0o700)
    for filename, content in files.items():
        (project_dir / filename).write_text(content, encoding="utf-8")
    data_dir = arm_dir / "julius-data"
    data_dir.mkdir(mode=0o700)
    settings_path, mcp_path = arm_dir / "settings.json", arm_dir / "mcp.json"
    arm_project = f"{project_id}-{run_dir.name}-{task['id']}-{name}"
    command = "cat README.md notes.py store.py routes.py"
    plan = build_launch_plan(
        project_id=arm_project, data_dir=data_dir, settings_path=settings_path,
        mcp_path=mcp_path, python_executable=python_executable,
        claude_executable=claude_executable, task_id=task["id"],
        enable_safe_hook=name == "safe_hook",
        claude_args=(
            "--print", "--output-format", "stream-json", "--verbose",
            "--include-hook-events", "--no-session-persistence", "--restricted",
            "--strict-mcp-config", "--permission-mode", "dontAsk",
            "--permission-prompts", "none", "--tools", "Bash",
            "--allowedTools", f"Bash({command})", "mcp__julius-recovery__restore_artifact",
            "--max-turns", str(max_turns), "--max-budget-usd", str(max_budget_usd),
            *(["--model", model] if model is not None else []),
        ),
    )
    settings = plan.settings
    settings.setdefault("hooks", {})["PreToolUse"] = [{
        "matcher": "*", "hooks": [{"type": "command", "command": shlex.join([
            python_executable, "-m", "julius.repo_task_pilot", "--gate",
            str(arm_dir / "command-used"),
        ])}],
    }]
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    mcp_path.write_text(json.dumps(plan.mcp_config), encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [
        str(Path(__file__).resolve().parent.parent), env.get("PYTHONPATH", ""),
    ]))
    prompt = (
        f"Read the frozen repository using this exact Bash command once: {command}\n"
        f"Then answer this question with only the requested exact value: {task['question']}\n"
        "Do not use other commands or tools."
    )
    started = time.monotonic()
    stdout, stderr, exit_code, failure = "", "", -1, None
    try:
        completed = runner(list(plan.claude_command), input=prompt, text=True,
                           capture_output=True, timeout=timeout_seconds, check=False,
                           cwd=project_dir, env=env)
        stdout, stderr, exit_code = _as_text(completed.stdout), _as_text(completed.stderr), completed.returncode
    except subprocess.TimeoutExpired as error:
        failure = "timeout"
        stdout, stderr = _as_text(error.stdout), _as_text(error.stderr)
    except OSError as error:
        failure, stderr = f"launch_error:{type(error).__name__}", str(error)
    latency = time.monotonic() - started
    stdout_path, stderr_path = arm_dir / "stdout.jsonl", arm_dir / "stderr.txt"
    stdout_path.write_text(stdout[:MAX_STREAM_BYTES], encoding="utf-8")
    stderr_path.write_text(stderr[:MAX_STREAM_BYTES], encoding="utf-8")
    try:
        parsed = parse_stream_json(stdout, exit_code=exit_code)
    except ValueError:
        parsed = parse_stream_json("", exit_code=exit_code)
        failure = failure or "oversized_stream"
    evidence = _stream_evidence(stdout, command)
    passed = bool(parsed["complete"] and parsed["output"] == task["answer"]
                  and evidence["bash_requests"] == 1 and evidence["bash_results"] == 1
                  and evidence["unexpected_tool_requests"] == 0)
    result = {
        "task_id": task["id"], "language": task["language"], "kind": task["kind"],
        "arm": name, "project_id": arm_project, "passed": passed,
        "complete": parsed["complete"], "error": failure or parsed["error"],
        "exit_code": exit_code, "result_subtype": parsed["result_subtype"],
        "session_id": parsed["session_id"], "actual_model": parsed["actual_model"],
        "observed_models": parsed["observed_models"], "usage": parsed["usage"],
        "cost_usd": parsed["cost_usd"], "cost_scope": parsed["cost_scope"],
        "latency_seconds": latency, "answer": parsed["output"],
        "expected_answer": task["answer"], **evidence,
        "stdout_path": str(stdout_path), "stderr_path": str(stderr_path),
    }
    (arm_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def run_repo_task_pilot(*, work_dir: Path, project_id: str, max_turns: int,
                        max_budget_usd: float, timeout_seconds: float,
                        model: str | None = None, task_ids: tuple[str, ...] | None = None,
                        corpus_path: Path = CORPUS_PATH,
                        python_executable: str = sys.executable,
                        claude_executable: str = "claude",
                        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
                        ) -> dict[str, Any]:
    """Run selected frozen tasks in paired client sessions; never call by default."""
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("project_id must be non-empty")
    if type(max_turns) is not int or not 1 <= max_turns <= 100:
        raise ValueError("max_turns must be between 1 and 100")
    if type(max_budget_usd) not in (int, float) or not math.isfinite(max_budget_usd) or max_budget_usd <= 0:
        raise ValueError("max_budget_usd must be positive and finite")
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive and finite")
    if model is not None and (not isinstance(model, str) or not model.strip() or "\x00" in model):
        raise ValueError("model must be a non-empty name")
    raw, corpus = _corpus(Path(corpus_path))
    by_id = {task["id"]: task for task in corpus["tasks"]}
    selected = list(by_id) if task_ids is None else list(task_ids)
    if not selected or len(set(selected)) != len(selected) or any(ident not in by_id for ident in selected):
        raise ValueError("task_ids must be unique frozen task IDs")
    root = Path(work_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_dir = root / f"repo-task-pilot-{uuid.uuid4()}"
    run_dir.mkdir(mode=0o700)
    corpus_hash = hashlib.sha256(raw).hexdigest()
    registration = {"corpus_sha256": corpus_hash, "corpus_bytes": len(raw),
                    "task_ids": selected, "source": str(Path(corpus_path).resolve())}
    (run_dir / "corpus-registration.json").write_text(json.dumps(registration, indent=2), encoding="utf-8")
    report: dict[str, Any] = {
        "run_dir": str(run_dir), "corpus_sha256": corpus_hash,
        "task_ids": selected, "limits_per_arm": {
            "max_turns": max_turns, "max_budget_usd": max_budget_usd,
            "timeout_seconds": timeout_seconds},
        "arms": [], "conclusion": "exploratory_descriptive_pair_only",
    }
    report_path = run_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for ident in selected:
        for name in ("baseline", "safe_hook"):
            try:
                result = _arm(
                    run_dir=run_dir, task=by_id[ident], files=corpus["files"],
                    name=name, project_id=project_id, max_turns=max_turns,
                    max_budget_usd=max_budget_usd, timeout_seconds=timeout_seconds,
                    model=model, python_executable=python_executable,
                    claude_executable=claude_executable, runner=runner,
                )
            except Exception as error:
                result = {"task_id": ident, "arm": name, "passed": False,
                          "complete": False, "error": f"internal_error:{type(error).__name__}"}
            report["arms"].append(result)
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "--gate":
        raise SystemExit("usage: python -m julius.repo_task_pilot --gate ONCE_FILE")
    raw = sys.stdin.buffer.read(65537)
    try:
        event = json.loads(raw) if len(raw) <= 65536 else None
    except (UnicodeError, json.JSONDecodeError):
        event = None
    decision = gate_hook_event(event, once_file=Path(sys.argv[2]),
                               command="cat README.md notes.py store.py routes.py")
    if decision is not None:
        print(json.dumps(decision))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
