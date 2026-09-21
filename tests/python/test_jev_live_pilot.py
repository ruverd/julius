"""No network calls: pilot safety and replay coverage with an injected gateway."""

import json

import pytest

from julius.jev import JevAnswer
from julius.jev_live_pilot import run_pilot
from julius.jev_shadow_eval import load_frozen_registration
from julius.sdk import Julius


class StubGateway:
    def __init__(self, model="jev-1.13.0"):
        self.model = model
        self.calls = []

    def choose(self, state, eligible_actions, timeout_seconds):
        self.calls.append((state, eligible_actions))
        return JevAnswer(eligible_actions[0], 0.9, 0.0001, 100, 1, self.model)


def options(tmp_path, gateway):
    return dict(journal_dir=tmp_path / "journal", julius=Julius(tmp_path / "ledger"),
        api_key="fixture", input_usd_per_million=1.0, max_input_tokens_per_call=1000,
        total_budget_usd=0.01, project_id="pilot", session_id="run", price_source="caller_fixture",
        price_date="2026-09-21", gateway=gateway)


def test_pilot_calls_only_optional_cases_and_journals(tmp_path):
    gateway = StubGateway()
    args = options(tmp_path, gateway)
    try:
        replay = run_pilot(**args)
    finally:
        args["julius"].close()
    assert replay["captured_cases"] == 5
    assert replay["missing_case_ids"] == []
    assert len(gateway.calls) == 5
    assert all(set(state) == set(load_frozen_registration().cases[0].state.model_dump()) for state, _ in gateway.calls)
    assert len(list((tmp_path / "journal").glob("*.attempting.json"))) == 5
    manifest = json.loads((tmp_path / "journal" / "manifest.json").read_text())
    assert len(manifest["deterministic_bypass_case_ids"]) == 1
    assert manifest["model_id"] == "jev-1.13.0"
    assert "api_key" not in json.dumps(manifest)


def test_budget_rejected_before_call_or_journal(tmp_path):
    gateway = StubGateway()
    args = options(tmp_path, gateway)
    args["total_budget_usd"] = 0.0001
    try:
        with pytest.raises(ValueError, match="Modeled maximum"):
            run_pilot(**args)
    finally:
        args["julius"].close()
    assert gateway.calls == []
    assert not (tmp_path / "journal").exists()


def test_model_mismatch_stops_and_remains_missing(tmp_path):
    gateway = StubGateway("jev-other")
    args = options(tmp_path, gateway)
    try:
        replay = run_pilot(**args)
    finally:
        args["julius"].close()
    assert len(gateway.calls) == 1
    assert replay["captured_cases"] == 0
    assert len(replay["missing_case_ids"]) == 5
    mismatch = list((tmp_path / "journal").glob("*.model_mismatch.json"))
    assert len(mismatch) == 1
    assert json.loads(mismatch[0].read_text())["cost_usd"] is None


@pytest.mark.parametrize("bad_date", ["2026-9-21", "2026-02-30", "tomorrow", "2026-09-21T00:00:00"])
def test_invalid_price_date_rejected_before_call(tmp_path, bad_date):
    gateway = StubGateway()
    args = options(tmp_path, gateway)
    args["price_date"] = bad_date
    try:
        with pytest.raises(ValueError, match="Price date"):
            run_pilot(**args)
    finally:
        args["julius"].close()
    assert gateway.calls == []
    assert not (tmp_path / "journal").exists()


@pytest.mark.parametrize("tokens,cost", [(1001, 0.0001), (100, 0.0011)])
def test_exceeded_per_call_assumption_stops_without_capture(tmp_path, tokens, cost):
    class ExceedingGateway(StubGateway):
        def choose(self, state, eligible_actions, timeout_seconds):
            self.calls.append((state, eligible_actions))
            return JevAnswer(eligible_actions[0], 0.9, cost, tokens, 1, self.model)

    gateway = ExceedingGateway()
    args = options(tmp_path, gateway)
    try:
        replay = run_pilot(**args)
    finally:
        args["julius"].close()
    assert len(gateway.calls) == 1
    assert replay["captured_cases"] == 0
    assert len(replay["missing_case_ids"]) == 5
    assert len(list((tmp_path / "journal").glob("*.assumption_invalid.json"))) == 1
