"""Fixture-only integration: no provider request or credentials leave this test."""

import json
from pathlib import Path
from urllib.error import URLError

from julius.cli import run
from julius.reporting import render_csv
from julius.sdk import Julius
from julius.xai import XAIResult


def test_xai_sdk_records_input_output_and_actual_model_separately(tmp_path: Path):
    request = {
        "model": "alias-requested",
        "input": [
            {"role": "system", "content": "Preserve this instruction."},
            {"role": "user", "content": "Answer once."},
        ],
        "tools": [{"type": "function", "name": "lookup", "parameters": {"type": "object"}}],
    }
    response = {
        "id": "response-1", "model": "grok-actual", "status": "completed",
        "usage": {
            "input_tokens": 120, "output_tokens": 30, "total_tokens": 150,
            "cost_in_usd_ticks": 37_756_000,
            "input_tokens_details": {"cached_tokens": 40},
            "output_tokens_details": {"reasoning_tokens": 10},
        },
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "Done"}]}],
    }
    observed = []

    def transport(body, headers):
        observed.append(json.loads(body))
        assert headers["Authorization"] == "Bearer test-key"
        return json.dumps(response).encode()

    with Julius(tmp_path) as julius:
        result = julius.send_xai(
            request, api_key="test-key", project_id="app", session_id="s1", task_id="TASK-1",
            transport=transport,
        )
        usage = julius.ledger.events()[0]
        assert usage["modelId"] == "grok-actual"
        assert usage["payload"]["inputTokens"] == 120
        assert usage["payload"]["outputTokens"] == 30
        assert usage["payload"]["cacheReadTokens"] == 40
        assert usage["payload"]["complete"] is True
        assert usage["payload"]["costUsd"] == 0.0037756
        assert usage["payload"]["costProvenance"]["chargeField"] == "usage.cost_in_usd_ticks"
        assert result["requestedModel"] == "alias-requested"
        assert julius.report()["financialSavingsUsd"] is None
        assert julius.report()["providerChargedUsd"]["total"] == 0.0037756
        assert julius.report()["modeledCostUsd"]["total"] is None
        assert "provider_charged_usd" in render_csv(julius.report())
    assert observed == [request]


def test_xai_transport_failure_is_incomplete_and_unknown(tmp_path: Path):
    def failed(_body, _headers):
        raise URLError("network")

    with Julius(tmp_path) as julius:
        result = julius.send_xai(
            {"model": "grok", "input": "Hi"}, api_key="test-key",
            project_id="app", session_id="s1", transport=failed,
        )
        usage = julius.ledger.events()[0]
        assert result["complete"] is False
        assert usage["evidence"] == "runtime_reported"
        assert usage["payload"]["inputTokens"] is None
        assert usage["payload"]["outputTokens"] is None
        assert usage["payload"]["costUsd"] is None


def test_cli_requires_dedicated_key_before_any_send(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    request = tmp_path / "request.json"
    request.write_text('{"model":"grok","input":"Hi"}')
    import pytest

    with pytest.raises(ValueError, match="XAI_API_KEY"):
        run(["run", "--agent", "grok", "--request", str(request),
             "--project", "app", "--data-dir", str(tmp_path / "store")])


def test_cli_explicit_grok_run_records_fixture_usage(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("XAI_API_KEY", "fixture-key")
    request = tmp_path / "request.json"
    request.write_text('{"model":"grok-fixture","input":"Hi","store":false}')
    observed = []

    def fixture_send(self, payload, key, transport=None):
        observed.append((payload, key))
        return XAIResult(
            "grok-fixture", "grok-reported", "response-1", True,
            10, 3, 2, None, 13,
            {"input_tokens": 10, "output_tokens": 3, "cost_in_usd_ticks": 100_000},
            {"id": "response-1", "model": "grok-reported", "status": "completed"},
            cost_ticks=100_000,
        )

    monkeypatch.setattr("julius.sdk.XAIAdapter.send_once", fixture_send)
    store = tmp_path / "store"
    assert run(["run", "--agent", "grok", "--request", str(request),
                "--project", "app", "--data-dir", str(store)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["actualModel"] == "grok-reported"
    assert observed == [({"model": "grok-fixture", "input": "Hi", "store": False}, "fixture-key")]
    with Julius(store) as julius:
        assert julius.report()["providerChargedUsd"]["total"] == 0.00001
