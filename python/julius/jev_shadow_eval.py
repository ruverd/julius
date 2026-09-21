"""Offline evaluation of prerecorded Jev Choice answers against frozen policy labels."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

Action = Literal["keep", "retrieve", "compress"]
ACTIONS: tuple[Action, ...] = ("keep", "retrieve", "compress")


class CaseState(BaseModel):
    """The exact, bounded metadata vocabulary accepted by the Jev boundary."""

    model_config = ConfigDict(extra="forbid", strict=True)
    input_tokens: StrictInt = Field(ge=0, le=1_000_000_000)
    estimated_reduction_tokens: StrictInt = Field(ge=0, le=1_000_000_000)
    artifact_recoverable: StrictBool
    has_protected_content: StrictBool
    model_local: StrictBool
    repetitive_content: StrictBool


class LabeledCase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: StrictStr = Field(min_length=1)
    label: Action
    eligible_actions: tuple[Action, ...] = Field(min_length=1)
    rationale: StrictStr = Field(min_length=1)
    state: CaseState
    evaluation_mode: Literal["deterministic_only", "optional_jev_shadow"]

    @model_validator(mode="after")
    def valid_label(self) -> LabeledCase:
        if len(set(self.eligible_actions)) != len(self.eligible_actions):
            raise ValueError("Eligible actions must be unique")
        if self.label not in self.eligible_actions:
            raise ValueError("Label must be eligible")
        if self.state.has_protected_content and self.evaluation_mode != "deterministic_only":
            raise ValueError("Protected content must be deterministic only")
        if self.evaluation_mode == "deterministic_only" and self.eligible_actions != ("keep",):
            raise ValueError("Deterministic-only cases must allow only keep")
        return self


class Registration(BaseModel):
    """Fixed label set; register before inspecting captures."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["2"]
    registration_id: StrictStr = Field(min_length=1)
    cases: tuple[LabeledCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self) -> Registration:
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("Case IDs must be unique")
        return self


class CapturedChoice(BaseModel):
    """Already captured answer metadata. This schema has no transport or prompt fields."""

    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: StrictStr = Field(min_length=1)
    choice: Action
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    input_tokens: StrictInt | None = Field(default=None, ge=0)
    output_tokens: StrictInt | None = Field(default=None, ge=0)
    actual_model: StrictStr | None = None


def load_frozen_registration() -> Registration:
    path = Path(__file__).parent / "data" / "jev_shadow_cases.json"
    return Registration.model_validate_json(path.read_text(encoding="utf-8"))


def evaluate_replay(
    registration: Registration, captures: tuple[CapturedChoice, ...]
) -> dict[str, object]:
    """Score one captured Choice per case without invoking a gateway or changing routing."""
    by_id = {case.case_id: case for case in registration.cases
             if case.evaluation_mode == "optional_jev_shadow"}
    deterministic_ids = sorted(case.case_id for case in registration.cases
                               if case.evaluation_mode == "deterministic_only")
    seen: set[str] = set()
    for capture in captures:
        if capture.case_id not in by_id:
            raise ValueError(f"Unregistered case: {capture.case_id}")
        if capture.case_id in seen:
            raise ValueError(f"Duplicate capture: {capture.case_id}")
        seen.add(capture.case_id)

    manifest = registration.model_dump(mode="json")
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=False).encode("utf-8")).hexdigest()
    confusion = {label: {choice: 0 for choice in ACTIONS} for label in ACTIONS}
    bins: dict[str, dict[str, float | int | None]] = {
        "0.0-0.2": {"count": 0, "mean_confidence": None, "accuracy": None},
        "0.2-0.4": {"count": 0, "mean_confidence": None, "accuracy": None},
        "0.4-0.6": {"count": 0, "mean_confidence": None, "accuracy": None},
        "0.6-0.8": {"count": 0, "mean_confidence": None, "accuracy": None},
        "0.8-1.0": {"count": 0, "mean_confidence": None, "accuracy": None},
    }
    sums = [[0.0, 0.0, 0.0] for _ in range(5)]
    correct = 0
    brier_sum = 0.0
    invalid_choices = 0
    known_cost = 0.0
    unknown_cost = 0
    known_input = 0
    unknown_input = 0
    known_output = 0
    unknown_output = 0
    for capture in captures:
        case = by_id[capture.case_id]
        valid = capture.choice in case.eligible_actions
        hit = valid and capture.choice == case.label
        confusion[case.label][capture.choice] += 1
        correct += int(hit)
        invalid_choices += int(not valid)
        brier_sum += (capture.confidence - float(hit)) ** 2
        index = min(int(capture.confidence * 5), 4)
        sums[index][0] += 1
        sums[index][1] += capture.confidence
        sums[index][2] += int(hit)
        if capture.cost_usd is None:
            unknown_cost += 1
        else:
            known_cost += capture.cost_usd
        if capture.input_tokens is None:
            unknown_input += 1
        else:
            known_input += capture.input_tokens
        if capture.output_tokens is None:
            unknown_output += 1
        else:
            known_output += capture.output_tokens
    for name, values in zip(bins, sums, strict=True):
        count, confidence_sum, hit_sum = values
        if count:
            bins[name] = {"count": int(count), "mean_confidence": confidence_sum / count,
                          "accuracy": hit_sum / count}
    count = len(captures)
    complete = count == len(by_id)
    return {
        "scope": "offline_jev_shadow_replay",
        "registration_id": registration.registration_id,
        "registration_sha256": digest,
        "planned_cases": len(registration.cases),
        "planned_shadow_cases": len(by_id),
        "deterministic_only_case_ids": deterministic_ids,
        "captured_cases": count,
        "missing_case_ids": sorted(set(by_id) - seen),
        "coverage": count / len(by_id) if by_id else None,
        "confusion": confusion,
        "correct": correct,
        "accuracy": correct / count if count else None,
        "ineligible_choices": invalid_choices,
        "brier_score": brier_sum / count if count else None,
        "calibration_bins": bins,
        "auxiliary_cost_usd": known_cost if complete and unknown_cost == 0 else None,
        "known_auxiliary_cost_usd": known_cost,
        "unknown_cost_captures": unknown_cost,
        "input_tokens": known_input if complete and unknown_input == 0 else None,
        "known_input_tokens": known_input,
        "unknown_input_captures": unknown_input,
        "output_tokens": known_output if complete and unknown_output == 0 else None,
        "known_output_tokens": known_output,
        "unknown_output_captures": unknown_output,
        "production_action_changed": False,
    }
