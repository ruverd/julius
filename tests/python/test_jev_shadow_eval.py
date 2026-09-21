"""Offline Jev Choice replay; no transport or production decision is imported."""

import pytest
from pydantic import ValidationError

from julius.jev_shadow_eval import (
    CapturedChoice, Registration, evaluate_replay, load_frozen_registration,
)


def test_frozen_registration_and_partial_replay_preserve_unknown_cost():
    registration = load_frozen_registration()
    assert len(registration.cases) == 6
    report = evaluate_replay(registration, (
        CapturedChoice(case_id="protected-content", choice="keep", confidence=0.9,
                       cost_usd=0.002, input_tokens=20, output_tokens=2),
        CapturedChoice(case_id="repeated-large-context", choice="keep", confidence=0.8),
    ))
    assert report["coverage"] == 2 / 6
    assert report["confusion"]["keep"]["keep"] == 1
    assert report["confusion"]["compress"]["keep"] == 1
    assert report["accuracy"] == 0.5
    assert report["brier_score"] == pytest.approx((0.1**2 + 0.8**2) / 2)
    assert report["calibration_bins"]["0.8-1.0"]["accuracy"] == 0.5
    assert report["auxiliary_cost_usd"] is None
    assert report["known_auxiliary_cost_usd"] == 0.002
    assert report["unknown_cost_captures"] == 1
    assert report["input_tokens"] is None
    assert report["production_action_changed"] is False


def test_empty_replay_has_null_metrics_and_complete_missing_list():
    registration = load_frozen_registration()
    report = evaluate_replay(registration, ())
    assert report["coverage"] == 0
    assert report["accuracy"] is None
    assert report["brier_score"] is None
    assert report["auxiliary_cost_usd"] is None
    assert len(report["missing_case_ids"]) == 6


def test_partial_replay_known_captures_are_subtotals_not_full_totals():
    registration = load_frozen_registration()
    report = evaluate_replay(registration, (
        CapturedChoice(case_id="protected-content", choice="keep", confidence=0.9,
                       cost_usd=0.002, input_tokens=20, output_tokens=2),
    ))
    assert report["coverage"] == 1 / 6
    assert report["known_auxiliary_cost_usd"] == 0.002
    assert report["auxiliary_cost_usd"] is None
    assert report["known_input_tokens"] == 20
    assert report["input_tokens"] is None
    assert report["output_tokens"] is None


def test_replay_rejects_unregistered_and_duplicate_captures():
    registration = load_frozen_registration()
    capture = CapturedChoice(case_id="protected-content", choice="keep", confidence=1)
    with pytest.raises(ValueError, match="Duplicate capture"):
        evaluate_replay(registration, (capture, capture))
    with pytest.raises(ValueError, match="Unregistered case"):
        evaluate_replay(registration, (CapturedChoice(case_id="unknown", choice="keep",
                                                      confidence=1),))


def test_schema_rejects_invalid_confidence_cost_and_label():
    with pytest.raises(ValidationError):
        CapturedChoice(case_id="x", choice="keep", confidence=1.1)
    with pytest.raises(ValidationError):
        CapturedChoice(case_id="x", choice="keep", confidence=0.5, cost_usd=-1)
    with pytest.raises(ValidationError):
        Registration.model_validate({"schema_version": "1", "registration_id": "x", "cases": [
            {"case_id": "x", "label": "retrieve", "eligible_actions": ["keep"],
             "rationale": "Invalid label"}]})
