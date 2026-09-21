"""Explicit bounded Claude print session and conservative final-usage parsing."""

from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .claude_runner import build_launch_plan


_COUNTERS = (
    "input_tokens", "output_tokens", "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def _counter(usage: dict[str, Any], name: str) -> int | None:
    value = usage.get(name)
    return value if type(value) is int and value >= 0 else None


def parse_stream_json(stdout: str, *, exit_code: int) -> dict[str, Any]:
    """Use only final result totals; never sum nested assistant/message counters."""
    if len(stdout.encode("utf-8")) > 10_000_000:
        raise ValueError("Claude stream exceeds 10 MB")
    final: dict[str, Any] | None = None
    models: set[str] = set()
    malformed = False
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            malformed = True
            continue
        if not isinstance(event, dict):
            malformed = True
            continue
        if event.get("type") == "assistant":
            message = event.get("message")
            model = message.get("model") if isinstance(message, dict) else None
            if isinstance(model, str) and model:
                models.add(model)
        elif event.get("type") == "result":
            if final is not None:
                malformed = True
            final = event
    model_usage = final.get("modelUsage") if final else None
    if isinstance(model_usage, dict):
        models.update(key for key in model_usage if isinstance(key, str) and key)
    usage = final.get("usage") if final else None
    totals = {name: _counter(usage, name) if isinstance(usage, dict) else None
              for name in _COUNTERS}
    cost = final.get("total_cost_usd") if final else None
    if not isinstance(cost, (int, float)) or isinstance(cost, bool):
        cost = None
    elif not math.isfinite(cost) or cost < 0:
        cost = None
    complete = bool(
        final is not None and exit_code == 0 and final.get("is_error") is False
        and final.get("subtype") == "success" and not malformed
    )
    return {
        "scope": "claude_session_delta",
        "complete": complete,
        "error": None if complete else (
            "malformed_stream" if malformed else
            "missing_result" if final is None else
            "client_error_or_incomplete"
        ),
        "exit_code": exit_code,
        "session_id": final.get("session_id") if final and isinstance(final.get("session_id"), str) else None,
        "actual_model": next(iter(models)) if len(models) == 1 else None,
        "observed_models": sorted(models),
        "usage": totals,
        "cost_usd": float(cost) if cost is not None else None,
        "cost_scope": "client_reported_session_total" if cost is not None else None,
    }


def run_claude_print(
    *, prompt: str, project_id: str, data_dir: Path,
    max_turns: int, max_budget_usd: float, timeout_seconds: float,
    task_id: str | None = None,
    python_executable: str = sys.executable,
    claude_executable: str = "claude",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Run one explicit client session; Julius persists no raw prompt."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Prompt must be non-empty")
    if type(max_turns) is not int or not 1 <= max_turns <= 100:
        raise ValueError("max_turns must be between 1 and 100")
    if (type(max_budget_usd) not in (int, float) or not math.isfinite(max_budget_usd)
            or max_budget_usd <= 0):
        raise ValueError("max_budget_usd must be positive and finite")
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0):
        raise ValueError("timeout_seconds must be positive and finite")
    with tempfile.TemporaryDirectory(prefix="julius-claude-print-") as directory:
        settings_path = Path(directory) / "settings.json"
        mcp_path = Path(directory) / "mcp.json"
        plan = build_launch_plan(
            project_id=project_id, data_dir=data_dir,
            settings_path=settings_path, mcp_path=mcp_path,
            task_id=task_id, python_executable=python_executable,
            claude_executable=claude_executable,
            claude_args=(
                "--print", "--output-format", "stream-json", "--verbose",
                "--no-session-persistence", "--max-turns", str(max_turns),
                "--max-budget-usd", str(max_budget_usd),
            ),
        )
        settings_path.write_text(json.dumps(plan.settings), encoding="utf-8")
        mcp_path.write_text(json.dumps(plan.mcp_config), encoding="utf-8")
        try:
            completed = runner(
                list(plan.claude_command), input=prompt, text=True, capture_output=True,
                timeout=timeout_seconds, check=False,
            )
        except subprocess.TimeoutExpired:
            return parse_stream_json("", exit_code=-1)
        return parse_stream_json(completed.stdout, exit_code=completed.returncode)
