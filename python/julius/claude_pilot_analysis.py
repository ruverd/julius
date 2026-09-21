"""Offline validation and descriptive analysis of frozen Claude pilot reports."""

from __future__ import annotations

import random
from typing import Any

from .claude_pair import PILOT_TASKS
from .claude_pilot import _FROZEN_CORPUS, _FROZEN_FIELDS, _canonical_hash
from .evaluation import Trial, analyze_paired_trials


def _counter(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer or null")
    return value


def _nonnegative_float(value: Any, field: str) -> float | None:
    if value is None:
        return None
    import math
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{field} must be a finite nonnegative number or null")
    return float(value)


def analyze_claude_pilot_report(
    report: dict[str, Any], *, seed: int = 0, resamples: int = 2000,
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Validate the full frozen corpus and compare observed session totals offline."""
    if not isinstance(report, dict) or report.get("corpus_sha256") != _canonical_hash(_FROZEN_CORPUS):
        raise ValueError("Pilot corpus hash mismatch")
    if report.get("complete") is not True:
        raise ValueError("Pilot report is incomplete")
    tasks = report.get("tasks")
    expected_tasks = [
        {"id": task["id"], "language": task["language"],
         "expected_answer": task["answer"],
         "context_kind": "compact" if task["id"].startswith("compact") else "repetitive",
         "task_sha256": _canonical_hash({key: task[key] for key in _FROZEN_FIELDS})}
        for task in PILOT_TASKS
    ]
    if tasks != expected_tasks:
        raise ValueError("Pilot task manifest mismatch")
    attempts = report.get("attempts")
    order = report.get("order")
    if not isinstance(attempts, list) or not isinstance(order, list) or len(attempts) != 12 or len(order) != 12:
        raise ValueError("Pilot requires exactly twelve attempts and order entries")
    order_seed = report.get("order_seed")
    if type(order_seed) is not int:
        raise ValueError("Pilot order seed must be an integer")
    rng = random.Random(order_seed)
    expected_order: list[dict[str, str | int]] = []
    for task in PILOT_TASKS:
        arms = ["baseline", "safe_hook"]
        rng.shuffle(arms)
        for arm in arms:
            expected_order.append({"execution_sequence": len(expected_order) + 1,
                                   "task_id": task["id"], "arm": arm})
    if order != expected_order:
        raise ValueError("Pilot seeded order mismatch")
    by_id = {task["id"]: task for task in PILOT_TASKS}
    seen: set[tuple[str, str]] = set()
    trials: list[Trial] = []
    for sequence, (entry, attempt) in enumerate(zip(order, attempts, strict=True), 1):
        if not isinstance(entry, dict) or not isinstance(attempt, dict):
            raise ValueError("Invalid pilot execution entry")
        task_id = attempt.get("task_id")
        arm_id = attempt.get("arm")
        if task_id not in by_id or arm_id not in ("baseline", "safe_hook"):
            raise ValueError("Unknown task or arm")
        if entry != {"execution_sequence": sequence, "task_id": task_id, "arm": arm_id}:
            raise ValueError("Pilot execution sequence mismatch")
        if attempt.get("execution_sequence") != sequence:
            raise ValueError("Pilot attempt sequence mismatch")
        task = by_id[task_id]
        if attempt.get("task_sha256") != _canonical_hash({key: task[key] for key in _FROZEN_FIELDS}):
            raise ValueError("Pilot task hash mismatch")
        if attempt.get("language") != task["language"]:
            raise ValueError("Pilot language mismatch")
        key = (task_id, arm_id)
        if key in seen:
            raise ValueError("Duplicate pilot task arm")
        seen.add(key)
        passed = attempt.get("passed")
        if type(passed) is not bool:
            raise ValueError("Pilot passed must be boolean")
        graded = (
            attempt.get("complete") is True
            and attempt.get("answer") == task["answer"]
            and attempt.get("bash_requests") == 1
            and attempt.get("bash_results") == 1
            and attempt.get("unexpected_tool_requests") == 0
        )
        if passed != graded:
            raise ValueError("Pilot pass grade mismatch")
        if (attempt.get("client_version") != report.get("client_version")
                or attempt.get("cache_state") != report.get("cache_state")):
            raise ValueError("Pilot client environment mismatch")
        models = attempt.get("observed_models")
        actual_model = attempt.get("actual_model")
        if (not isinstance(models, list) or any(not isinstance(model, str) or not model
                                                for model in models)
                or models != sorted(set(models))
                or actual_model != (models[0] if len(models) == 1 else None)):
            raise ValueError("Pilot observed model fields disagree")
        usage = attempt.get("usage")
        if not isinstance(usage, dict):
            raise ValueError("Pilot usage must be an object")
        base_input = _counter(usage.get("input_tokens"), "input_tokens")
        cache_read = _counter(usage.get("cache_read_input_tokens"), "cache_read_input_tokens")
        cache_write = _counter(usage.get("cache_creation_input_tokens"), "cache_creation_input_tokens")
        input_total = (base_input + cache_read + cache_write
                       if base_input is not None and cache_read is not None
                       and cache_write is not None else None)
        trials.append(Trial(
            arm_id=arm_id, task_id=task_id, success=passed,
            input_tokens=input_total,
            output_tokens=_counter(usage.get("output_tokens"), "output_tokens"),
            cache_read_tokens=cache_read, cache_write_tokens=cache_write,
            cost_usd=_nonnegative_float(attempt.get("cost_usd"), "cost_usd"),
            latency_ms=(lambda seconds: seconds * 1000 if seconds is not None else None)(
                _nonnegative_float(attempt.get("latency_seconds"), "latency_seconds")),
        ))
    if seen != {(task["id"], arm) for task in PILOT_TASKS for arm in ("baseline", "safe_hook")}:
        raise ValueError("Pilot task coverage incomplete")
    paired = analyze_paired_trials(trials, baseline_arm="baseline", candidate_arm="safe_hook",
                                   seed=seed, resamples=resamples, confidence=confidence)
    observed_models = sorted({model for attempt in attempts
                              for model in attempt.get("observed_models", [])
                              if isinstance(model, str) and model})
    single_model = (len(observed_models) == 1 and all(
        attempt.get("actual_model") == observed_models[0] for attempt in attempts))
    return {
        "corpus_sha256": report["corpus_sha256"],
        "order_seed": report.get("order_seed"),
        "client_version": report.get("client_version"),
        "cache_state": report.get("cache_state"),
        "measurement_scope": "client_reported_session_totals_only",
        "requested_model": report.get("requested_model"),
        "observed_models": observed_models,
        "model_comparability": "same_observed_model" if single_model else "mixed_or_unknown",
        "interpretation": "descriptive_paired_differences_not_direct_savings_or_causal_effect",
        "trials": [trial.model_dump() for trial in trials],
        "attempts": attempts,
        "paired_analysis": paired,
    }
