import json
from pathlib import Path

import pytest

from julius.cli import run
from julius.jev import JevAnswer, ShadowPolicy
from julius.sdk import Julius


class FixtureGateway:
    def choose(self, state, eligible_actions, timeout_seconds):
        assert state == {"input_tokens": 200, "artifact_recoverable": True}
        assert eligible_actions == ("keep", "compress")
        return JevAnswer("compress", 0.95, 0.002, 25, 4, "jev-tested-fixture")


def test_jev_shadow_records_auxiliary_usage_without_changing_action(tmp_path: Path):
    with Julius(tmp_path) as julius:
        result = julius.evaluate_jev_shadow(
            state={"input_tokens": 200, "artifact_recoverable": True, "private_path": "/secret"},
            eligible_actions=("keep", "compress"),
            policy=ShadowPolicy(enabled=True, max_cost_usd=0.01),
            project_id="app", session_id="s1", task_id="TASK-1", gateway=FixtureGateway(),
            price_source="caller-configured-test", price_date="2026-09-21",
        )
        assert result["shadow"]["applied_action"] == "keep"
        assert result["shadow"]["proposed_action"] == "compress"
        events = julius.ledger.events()
        assert len(events) == 2
        usage = next(event for event in events if event["eventType"] == "usage")
        assert usage["payload"]["category"] == "auxiliary"
        assert usage["payload"]["inputTokens"] == 25
        assert usage["payload"]["outputTokens"] == 4
        assert usage["payload"]["costUsd"] == 0.002
        assert usage["payload"]["costProvenance"]["priceSource"] == "caller-configured-test"
        assert julius.report()["auxiliaryCostUsd"]["total"] == 0.002


def test_jev_unknown_price_stays_unavailable(tmp_path: Path):
    with Julius(tmp_path) as julius:
        julius.evaluate_jev_shadow(
            state={"input_tokens": 200, "artifact_recoverable": True},
            eligible_actions=("keep", "compress"),
            policy=ShadowPolicy(enabled=True, max_cost_usd=0.01),
            project_id="app", session_id="s1", gateway=FixtureGateway(),
        )
        usage = next(event for event in julius.ledger.events() if event["eventType"] == "usage")
        assert usage["payload"]["costUsd"] is None


def test_jev_cli_requires_key_before_network(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    state = tmp_path / "state.json"
    state.write_text('{"input_tokens":100}')
    with pytest.raises(ValueError, match="TYPESAFE_API_KEY"):
        run(["jev", "shadow", "--state-file", str(state), "--project", "app",
             "--post-call-threshold-usd", "0.01", "--data-dir", str(tmp_path / "store")])


def test_jev_cli_shadow_records_fixture_without_applying(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("TYPESAFE_API_KEY", "fixture-key")
    state = tmp_path / "state.json"
    state.write_text('{"input_tokens":200,"artifact_recoverable":true,"private_path":"/secret"}')
    monkeypatch.setattr(
        "julius.jev.TypeSafeGateway.choose",
        lambda self, metadata, actions, timeout: JevAnswer(
            "compress", 0.95, 0.002, 25, 4, "jev-reported"
        ),
    )
    store = tmp_path / "store"
    assert run(["jev", "shadow", "--state-file", str(state), "--project", "app",
                "--post-call-threshold-usd", "0.01", "--price-source", "fixture-price",
                "--price-date", "2026-09-21", "--data-dir", str(store)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["shadow"]["applied_action"] == "keep"
    assert printed["shadow"]["proposed_action"] == "compress"
    with Julius(store) as julius:
        assert julius.report()["auxiliaryCostUsd"]["total"] == 0.002
