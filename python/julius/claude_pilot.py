"""Opt-in, bounded bilingual Claude Code pilot over frozen synthetic tasks."""

from __future__ import annotations

import json
import hashlib
import random
import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .claude_pair import PILOT_TASKS, _arm


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


_FROZEN_FIELDS = ("id", "language", "command", "output", "answer", "prompt")
_FROZEN_CORPUS = [{key: task[key] for key in _FROZEN_FIELDS} for task in PILOT_TASKS]


def run_claude_pilot(
    *, work_dir: Path, project_id: str, max_turns: int,
    max_budget_usd: float, timeout_seconds: float, order_seed: int,
    model: str | None = None, client_version: str | None = None,
    cache_state: str | None = None,
    python_executable: str = sys.executable,
    claude_executable: str = "claude",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Run every frozen task in both arms; retain failed attempts and raw streams."""
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("project_id must be non-empty")
    if type(order_seed) is not int:
        raise ValueError("order_seed must be an integer")
    # Reuse the pair runner's validation before any external operation.
    if type(max_turns) is not int or not 1 <= max_turns <= 100:
        raise ValueError("max_turns must be between 1 and 100")
    import math
    if type(max_budget_usd) not in (int, float) or not math.isfinite(max_budget_usd) or max_budget_usd <= 0:
        raise ValueError("max_budget_usd must be positive and finite")
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive and finite")
    if model is not None and (not isinstance(model, str) or not model.strip() or "\x00" in model):
        raise ValueError("model must be a non-empty name")
    if client_version is not None and (not isinstance(client_version, str) or not client_version.strip()):
        raise ValueError("client_version must be a non-empty string")
    if cache_state is not None and (not isinstance(cache_state, str) or not cache_state.strip()):
        raise ValueError("cache_state must be a non-empty string")
    root = Path(work_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_dir = root / f"claude-pilot-{uuid.uuid4()}"
    run_dir.mkdir(mode=0o700)
    rng = random.Random(order_seed)
    attempts: list[dict[str, Any]] = []
    order: list[dict[str, str | int]] = []
    schedule: list[tuple[dict[str, str], str]] = []
    for task in PILOT_TASKS:
        arms = ["baseline", "safe_hook"]
        rng.shuffle(arms)
        for name in arms:
            schedule.append((task, name))
            order.append({"execution_sequence": len(order) + 1,
                          "task_id": task["id"], "arm": name})
    manifest = {
        "corpus_sha256": _canonical_hash(_FROZEN_CORPUS),
        "tasks": [{"id": task["id"], "language": task["language"],
                   "expected_answer": task["answer"],
                   "context_kind": "compact" if task["id"].startswith("compact") else "repetitive",
                   "task_sha256": _canonical_hash({key: task[key] for key in _FROZEN_FIELDS})}
                  for task in PILOT_TASKS],
        "order_seed": order_seed, "order": order,
        "requested_model": model, "client_version": client_version,
        "cache_state": cache_state,
        "limits_per_arm": {"max_turns": max_turns,
                           "max_budget_usd": max_budget_usd,
                           "timeout_seconds": timeout_seconds},
    }
    registration_path = run_dir / "registration.json"
    registration_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    registration_path.chmod(0o400)

    def save_report() -> dict[str, Any]:
        report = {
            "run_dir": str(run_dir), "registration_path": str(registration_path),
            **manifest, "attempts": attempts,
            "complete": len(attempts) == len(schedule),
            "measurement_scope": "client_reported_session_totals_only",
            "conclusion": "descriptive_pilot_only",
            "caveat": "Small paired pilot; cache state, client version, model behavior, and order may affect totals. No causal savings claim.",
        }
        staged = run_dir / "report.json.tmp"
        staged.write_text(json.dumps(report, indent=2), encoding="utf-8")
        staged.replace(run_dir / "report.json")
        return report

    save_report()
    for task, name in schedule:
        attempt_dir = run_dir / task["id"]
        attempt_dir.mkdir(mode=0o700, exist_ok=True)
        sequence = len(attempts) + 1
        task_hash = _canonical_hash({key: task[key] for key in _FROZEN_FIELDS})
        attempt = _arm(
            name=name, run_dir=attempt_dir, project_id=project_id,
            max_turns=max_turns, max_budget_usd=max_budget_usd,
            timeout_seconds=timeout_seconds, model=model,
            python_executable=python_executable,
            claude_executable=claude_executable, runner=runner, task=task,
        )
        attempt.update({"execution_sequence": sequence, "task_sha256": task_hash,
                        "client_version": client_version, "cache_state": cache_state})
        (attempt_dir / name / "result.json").write_text(
            json.dumps(attempt, indent=2), encoding="utf-8")
        attempts.append(attempt)
        save_report()
    return save_report()
