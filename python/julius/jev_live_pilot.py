"""Explicit, bounded Jev shadow pilot with a durable, single-attempt journal."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .jev import Action, JevAnswer, JevGateway, JevTransport, ShadowPolicy, TypeSafeGateway
from .jev_shadow_eval import CapturedChoice, Registration, evaluate_replay, load_frozen_registration
from .sdk import Julius

PINNED_MODEL = "jev-1.13.0"


class _CaptureGateway:
    def __init__(self, delegate: JevGateway) -> None:
        self.delegate = delegate
        self.answer: JevAnswer | None = None

    def choose(self, state: Mapping[str, object], eligible_actions: tuple[Action, ...], timeout_seconds: float) -> JevAnswer:
        answer = self.delegate.choose(state, eligible_actions, timeout_seconds)
        if answer.actual_model != PINNED_MODEL:
            answer = replace(answer, cost_usd=None)
        self.answer = answer
        return answer


def _write_json(path: Path, value: object) -> None:
    # Exclusive create makes an existing attempt impossible to replay accidentally.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        import os
        os.fsync(stream.fileno())


def run_pilot(
    *,
    journal_dir: str | Path,
    julius: Julius,
    api_key: str,
    input_usd_per_million: float,
    max_input_tokens_per_call: int,
    total_budget_usd: float,
    project_id: str,
    session_id: str,
    price_source: str,
    price_date: str,
    transport: JevTransport | None = None,
    gateway: JevGateway | None = None,
    registration: Registration | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """Run each optional frozen case once. A journal directory is never resumed.

    The input token bound is a caller assumption, not a verified provider hard cap.
    A new directory is required for every run; ambiguous attempts remain journaled.
    """
    registration = registration or load_frozen_registration()
    if registration.schema_version != "2":
        raise ValueError("Frozen registration v2 required")
    optional = [case for case in registration.cases if case.evaluation_mode == "optional_jev_shadow"]
    if not optional or any(case.evaluation_mode not in ("optional_jev_shadow", "deterministic_only") for case in registration.cases):
        raise ValueError("Invalid pilot case modes")
    if any(not case.case_id.isascii() or not all(c.isalnum() or c in "_-" for c in case.case_id) for case in registration.cases):
        raise ValueError("Case IDs must be safe journal filenames")
    if type(max_input_tokens_per_call) is not int or max_input_tokens_per_call <= 0:
        raise ValueError("Positive assumed maximum input tokens required")
    for value in (input_usd_per_million, total_budget_usd, timeout_seconds):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError("Positive finite rate, budget, and timeout required")
    modeled_max_usd = len(optional) * max_input_tokens_per_call * input_usd_per_million / 1_000_000
    if modeled_max_usd > total_budget_usd:
        raise ValueError("Modeled maximum exceeds total budget before any call")
    if not project_id or not session_id or not price_source or not price_date:
        raise ValueError("Project, session, and price provenance required")
    try:
        valid_price_date = date.fromisoformat(price_date).isoformat() == price_date
    except ValueError:
        valid_price_date = False
    if not valid_price_date:
        raise ValueError("Price date must be strict YYYY-MM-DD")
    delegate = gateway or TypeSafeGateway(api_key, input_usd_per_million=input_usd_per_million,
        output_usd_per_million=0.0, model_id=PINNED_MODEL, transport=transport)
    journal = Path(journal_dir)
    journal.mkdir(parents=True, exist_ok=False)
    _write_json(journal / "manifest.json", {
        "registration": registration.model_dump(mode="json"), "model_id": PINNED_MODEL,
        "input_usd_per_million": input_usd_per_million, "output_usd_per_million": 0.0,
        "max_input_tokens_per_call_assumption": max_input_tokens_per_call,
        "modeled_maximum_usd_assumption": modeled_max_usd, "total_budget_usd": total_budget_usd,
        "price_source": price_source, "price_date": price_date,
        "planned_optional_case_ids": [case.case_id for case in optional],
        "deterministic_bypass_case_ids": [case.case_id for case in registration.cases if case.evaluation_mode == "deterministic_only"],
    })
    captures: list[CapturedChoice] = []
    known_spend = 0.0
    for case in optional:
        # The marker is durable before the external call. Never revisit this run.
        _write_json(journal / f"{case.case_id}.attempting.json", {"case_id": case.case_id, "status": "attempting"})
        wrapper = _CaptureGateway(delegate)
        try:
            outcome = julius.evaluate_jev_shadow(
                state=case.state.model_dump(), eligible_actions=case.eligible_actions,
                policy=ShadowPolicy(enabled=True, max_cost_usd=total_budget_usd, timeout_seconds=timeout_seconds),
                project_id=project_id, session_id=session_id, task_id=case.case_id,
                gateway=wrapper, price_source=price_source, price_date=price_date,
            )
        except Exception as exc:
            _write_json(journal / f"{case.case_id}.failed.json", {"case_id": case.case_id, "status": "failed", "error_type": type(exc).__name__})
            break
        answer = wrapper.answer
        reason = outcome["shadow"]["reason"]
        if answer is None:
            _write_json(journal / f"{case.case_id}.failed.json", {"case_id": case.case_id, "status": "failed", "reason": reason})
            break
        if answer.actual_model != PINNED_MODEL:
            _write_json(journal / f"{case.case_id}.model_mismatch.json", {
                "case_id": case.case_id, "status": "model_mismatch", "actual_model": answer.actual_model,
                "expected_model": PINNED_MODEL, "cost_usd": None,
            })
            break
        per_call_modeled_max_usd = max_input_tokens_per_call * input_usd_per_million / 1_000_000
        if (answer.input_tokens is None or answer.input_tokens > max_input_tokens_per_call
                or answer.cost_usd is None or answer.cost_usd > per_call_modeled_max_usd):
            _write_json(journal / f"{case.case_id}.assumption_invalid.json", {
                "case_id": case.case_id, "status": "assumption_invalid",
                "input_tokens": answer.input_tokens, "cost_usd": answer.cost_usd,
                "max_input_tokens_per_call_assumption": max_input_tokens_per_call,
                "per_call_modeled_maximum_usd_assumption": per_call_modeled_max_usd,
            })
            break
        known_spend += answer.cost_usd
        if known_spend > total_budget_usd:
            _write_json(journal / f"{case.case_id}.failed.json", {"case_id": case.case_id, "status": "failed", "reason": "cost_unknown_or_budget_exceeded"})
            break
        try:
            capture = CapturedChoice.model_validate({
                "case_id": case.case_id, "choice": answer.choice, "confidence": answer.confidence,
                "cost_usd": answer.cost_usd, "input_tokens": answer.input_tokens,
                "output_tokens": answer.output_tokens, "actual_model": answer.actual_model,
            })
        except ValueError:
            _write_json(journal / f"{case.case_id}.failed.json", {"case_id": case.case_id, "status": "failed", "reason": "invalid_answer"})
            break
        _write_json(journal / f"{case.case_id}.capture.json", capture.model_dump(mode="json"))
        captures.append(capture)
    replay = evaluate_replay(registration, tuple(captures))
    _write_json(journal / "replay.json", replay)
    return replay
