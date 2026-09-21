"""Offline replay of frozen, paired task fixtures and complete attempt records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

from .evaluation import Trial, analyze_paired_trials


class FrozenFixture(BaseModel):
    """A caller-supplied task snapshot whose ID binds its exact JSON content."""

    model_config = ConfigDict(extra="forbid", strict=True)
    task_id: StrictStr = Field(min_length=1)
    fixture_id: StrictStr = Field(pattern=r"^[a-f0-9]{64}$")
    snapshot: dict[str, Any]

    @staticmethod
    def digest(task_id: str, snapshot: dict[str, Any]) -> str:
        encoded = json.dumps(
            {"task_id": task_id, "snapshot": snapshot},
            sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @model_validator(mode="after")
    def verify_id(self) -> FrozenFixture:
        if self.fixture_id != self.digest(self.task_id, self.snapshot):
            raise ValueError("Fixture ID does not match frozen snapshot")
        return self


class Attempt(BaseModel):
    """One observed attempt, including failed and retry attempts."""

    model_config = ConfigDict(extra="forbid", strict=True)
    fixture_id: StrictStr
    arm_id: StrictStr = Field(min_length=1)
    attempt_index: StrictInt = Field(ge=0)
    success: StrictBool
    input_tokens: StrictInt | None = Field(ge=0)
    output_tokens: StrictInt | None = Field(ge=0)
    cache_read_tokens: StrictInt | None = Field(ge=0)
    cache_write_tokens: StrictInt | None = Field(ge=0)
    auxiliary_tokens: StrictInt | None = Field(ge=0)
    cost_usd: StrictFloat | None = Field(ge=0, allow_inf_nan=False)
    latency_ms: StrictFloat | None = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def verify_counts(self) -> Attempt:
        for name in ("attempt_index", "input_tokens", "output_tokens", "cache_read_tokens",
                     "cache_write_tokens", "auxiliary_tokens"):
            value = getattr(self, name)
            if value is not None and type(value) is not int:
                raise ValueError(f"{name} must be an integer")
        if (self.input_tokens is not None and self.cache_read_tokens is not None
                and self.cache_write_tokens is not None
                and self.cache_read_tokens + self.cache_write_tokens > self.input_tokens):
            raise ValueError("Cache tokens exceed input tokens")
        return self


_METRICS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
            "auxiliary_tokens", "cost_usd", "latency_ms")


def replay_paired_fixtures(
    fixtures: Sequence[FrozenFixture], attempts: Sequence[Attempt], *,
    baseline_arm: str, candidate_arm: str, seed: int = 0,
) -> dict[str, Any]:
    """Aggregate supplied attempts; execute no task, provider, or external process."""
    if not fixtures:
        raise ValueError("At least one frozen fixture is required")
    if not baseline_arm or not candidate_arm or baseline_arm == candidate_arm:
        raise ValueError("Distinct arms are required")
    by_id = {item.fixture_id: item for item in fixtures}
    if len(by_id) != len(fixtures) or len({item.task_id for item in fixtures}) != len(fixtures):
        raise ValueError("Duplicate fixture ID or task ID")
    grouped: dict[tuple[str, str], list[Attempt]] = {}
    for attempt in attempts:
        if attempt.fixture_id not in by_id or attempt.arm_id not in (baseline_arm, candidate_arm):
            raise ValueError("Unknown fixture or arm")
        grouped.setdefault((attempt.fixture_id, attempt.arm_id), []).append(attempt)
    trials: list[Trial] = []
    for fixture in fixtures:
        for arm in (baseline_arm, candidate_arm):
            records = sorted(grouped.get((fixture.fixture_id, arm), []), key=lambda x: x.attempt_index)
            if not records or [item.attempt_index for item in records] != list(range(len(records))):
                raise ValueError("Each fixture and arm needs contiguous attempts from zero")
            if any(item.success for item in records[:-1]):
                raise ValueError("Attempts cannot continue after success")
            totals = {
                metric: sum(values) if all(value is not None for value in values) else None
                for metric in _METRICS
                for values in ([getattr(item, metric) for item in records],)
            }
            trials.append(Trial(
                arm_id=arm, task_id=fixture.task_id, success=records[-1].success,
                retries=len(records) - 1, **totals,
            ))
    analysis = analyze_paired_trials(
        trials, baseline_arm=baseline_arm, candidate_arm=candidate_arm, seed=seed,
    )
    return {
        "scope": "offline_fixture_replay",
        "fixture_ids": {item.task_id: item.fixture_id for item in fixtures},
        "attempts": [item.model_dump() for item in attempts],
        "analysis": analysis,
    }
