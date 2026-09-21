"""Offline analysis of explicitly supplied, paired task trials."""

from __future__ import annotations

from collections.abc import Sequence
import math
import random
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator


class Trial(BaseModel):
    """One successful or failed task run; totals include all retry attempts."""

    model_config = ConfigDict(extra="forbid", strict=True)

    arm_id: StrictStr = Field(min_length=1)
    task_id: StrictStr = Field(min_length=1)
    success: StrictBool
    input_tokens: StrictInt | None = Field(default=None, ge=0)
    output_tokens: StrictInt | None = Field(default=None, ge=0)
    cache_read_tokens: StrictInt | None = Field(default=None, ge=0)
    cache_write_tokens: StrictInt | None = Field(default=None, ge=0)
    auxiliary_tokens: StrictInt | None = Field(default=None, ge=0)
    cost_usd: StrictFloat | None = Field(default=None, ge=0, allow_inf_nan=False)
    latency_ms: StrictFloat | None = Field(default=None, ge=0, allow_inf_nan=False)
    retries: StrictInt = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_token_values(self) -> Trial:
        # StrictInt | None can otherwise coerce bool through Pydantic union behavior.
        for name in (
            "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
            "auxiliary_tokens", "retries",
        ):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a nonnegative integer or null")
        if (
            self.input_tokens is not None
            and self.cache_read_tokens is not None
            and self.cache_write_tokens is not None
            and self.cache_read_tokens + self.cache_write_tokens > self.input_tokens
        ):
            raise ValueError("Cache tokens cannot exceed input tokens")
        return self


_METRICS = (
    "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
    "auxiliary_tokens", "cost_usd", "latency_ms",
)


def _total(trials: Sequence[Trial], metric: str) -> int | float | None:
    values = [getattr(trial, metric) for trial in trials]
    return sum(values) if values and all(value is not None for value in values) else None


def _summary(trials: Sequence[Trial]) -> dict[str, Any]:
    attempts = sum(trial.retries + 1 for trial in trials)
    tasks = len(trials)
    successes = sum(trial.success for trial in trials)
    totals = {metric: _total(trials, metric) for metric in _METRICS}
    return {
        "attempted_tasks": tasks,
        "resolved_tasks": successes,
        "attempts": attempts,
        "retries": attempts - tasks,
        "successes": successes,
        "failures": sum(not trial.success for trial in trials),
        "success_rate": successes / tasks if tasks else None,
        "totals": totals,
        "per_attempt": {
            metric: value / attempts if value is not None and attempts else None
            for metric, value in totals.items()
        },
        "per_attempted_task": {
            metric: value / tasks if value is not None and tasks else None
            for metric, value in totals.items()
        },
        "per_resolved_task": {
            metric: value / successes if value is not None and successes else None
            for metric, value in totals.items()
        },
    }


def _percentile(sorted_values: Sequence[float], proportion: float) -> float:
    position = (len(sorted_values) - 1) * proportion
    lower = math.floor(position)
    upper = math.ceil(position)
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (
        position - lower
    )


def _bootstrap_interval(
    differences: Sequence[float | None], *, seed: int, resamples: int, confidence: float
) -> dict[str, float | int | None]:
    known = [value for value in differences if value is not None]
    result: dict[str, float | int | None] = {
        "sample_count": len(known), "lower": None, "upper": None,
    }
    if len(known) != len(differences) or len(known) < 2:
        return result
    rng = random.Random(seed)
    size = len(known)
    estimates = sorted(
        sum(known[rng.randrange(size)] for _ in range(size)) / size
        for _ in range(resamples)
    )
    tail = (1 - confidence) / 2
    result["lower"] = _percentile(estimates, tail)
    result["upper"] = _percentile(estimates, 1 - tail)
    return result


def analyze_paired_trials(
    trials: Sequence[Trial], *, baseline_arm: str, candidate_arm: str,
    seed: int = 0, resamples: int = 2000, confidence: float = 0.95,
) -> dict[str, Any]:
    """Compare arms only on identical task IDs, with signed baseline-minus-candidate savings.

    Each record represents one completed or failed task run and aggregates its retry
    attempts. Per-attempt values divide totals by retries + 1; per-resolved-task
    values include failed-run expenditure divided by successful runs. Neither
    reconstructs individual attempt usage or outcome. Unknown inputs propagate to null metrics.
    """
    if (type(seed) is not int or type(resamples) is not int or not 100 <= resamples <= 10_000
            or type(confidence) is not float or not 0 < confidence < 1):
        raise ValueError("Bootstrap requires an integer seed, 100–10000 resamples, and 0 < confidence < 1")
    if not baseline_arm or not candidate_arm or baseline_arm == candidate_arm:
        raise ValueError("Distinct, nonempty arm IDs required")
    by_key: dict[tuple[str, str], Trial] = {}
    for trial in trials:
        if trial.arm_id not in (baseline_arm, candidate_arm):
            raise ValueError(f"Unexpected arm: {trial.arm_id}")
        key = (trial.arm_id, trial.task_id)
        if key in by_key:
            raise ValueError(f"Duplicate arm/task pair: {key}")
        by_key[key] = trial
    base_ids = {task for arm, task in by_key if arm == baseline_arm}
    candidate_ids = {task for arm, task in by_key if arm == candidate_arm}
    paired_ids = sorted(base_ids & candidate_ids)
    baseline = [by_key[baseline_arm, task] for task in paired_ids]
    candidate = [by_key[candidate_arm, task] for task in paired_ids]
    base_summary = _summary(baseline)
    candidate_summary = _summary(candidate)
    savings = {
        metric: (
            base_summary["totals"][metric] - candidate_summary["totals"][metric]
            if base_summary["totals"][metric] is not None
            and candidate_summary["totals"][metric] is not None
            else None
        )
        for metric in _METRICS
    }
    interval_metrics = ("input_tokens", "output_tokens", "cost_usd", "latency_ms")
    intervals = {
        metric: _bootstrap_interval(
            [
                float(getattr(base, metric) - getattr(new, metric))
                if getattr(base, metric) is not None and getattr(new, metric) is not None
                else None
                for base, new in zip(baseline, candidate, strict=True)
            ],
            seed=seed, resamples=resamples, confidence=confidence,
        )
        for metric in interval_metrics
    }
    intervals["success_rate_difference"] = _bootstrap_interval(
        [float(new.success) - float(base.success)
         for base, new in zip(baseline, candidate, strict=True)],
        seed=seed, resamples=resamples, confidence=confidence,
    )
    return {
        "bootstrap": {
            "method": "paired_percentile", "seed": seed, "resamples": resamples,
            "confidence": confidence, "intervals": intervals,
        },
        "baseline_arm": baseline_arm,
        "candidate_arm": candidate_arm,
        "paired_task_ids": paired_ids,
        "unpaired_baseline_task_ids": sorted(base_ids - candidate_ids),
        "unpaired_candidate_task_ids": sorted(candidate_ids - base_ids),
        "baseline": base_summary,
        "candidate": candidate_summary,
        "savings": savings,
        "success_delta": candidate_summary["successes"] - base_summary["successes"],
        "paired_tasks": [
            {
                "task_id": task,
                "baseline_success": by_key[baseline_arm, task].success,
                "candidate_success": by_key[candidate_arm, task].success,
                "savings": {
                    metric: (
                        getattr(by_key[baseline_arm, task], metric)
                        - getattr(by_key[candidate_arm, task], metric)
                        if getattr(by_key[baseline_arm, task], metric) is not None
                        and getattr(by_key[candidate_arm, task], metric) is not None
                        else None
                    )
                    for metric in _METRICS
                },
            }
            for task in paired_ids
        ],
    }
