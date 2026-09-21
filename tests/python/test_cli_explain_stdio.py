"""Public CLI paths for offline task explanations and versioned stdio."""

import io
import json
from pathlib import Path
from uuid import uuid4

import pytest

from julius.cli import _stored_task_prices, _task_explanation, run
from julius.price_store import PriceSnapshot, PriceStore
from julius.sdk import Julius

FIXTURE = Path(__file__).parents[1] / "fixtures" / "events.jsonl"


def test_task_explanation_displays_output_comparison_provenance() -> None:
    data = {
        "taskId": "task", "coverageComplete": True, "observedInputTokens": 100,
        "observedOutputTokens": 10, "directInputReductionTokens": None,
        "outputSavingsTokens": -2, "outputSavingsEvidence": "controlled_experiment",
        "outputComparisonIdentity": {
            "providerId": "vendor", "modelId": "model", "tokenizerId": "tok",
            "tokenizerSources": ["fixture"],
        },
        "baselineId": "base", "baselineEvidence": "controlled_experiment",
        "baselineModeledCostUsd": None, "currentCostUsd": None,
        "extraOverheadUsd": 0, "netModeledSavingsUsd": None,
        "usageRecordsWithoutCallId": 0,
    }
    explanation = _task_explanation(data)
    assert "Comparative task output difference: -2" in explanation
    assert "'tokenizerId': 'tok'" in explanation


def test_task_explanation_preserves_unknown_baseline(tmp_path: Path, capsys) -> None:
    store = tmp_path / "store"
    events = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    with Julius(store) as julius:
        julius.ledger.record_many(events)
    assert run([
        "savings", "--task", "DEMO-1", "--explain", "--json",
        "--since", "2026-09-21T00:00:00Z", "--until", "2026-09-22T00:00:00Z",
        "--data-dir", str(store),
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["observedInputTokens"] is None
    assert result["baselineId"] is None
    assert result["netModeledSavingsUsd"] is None
    assert result["coverageComplete"] is False


def test_task_explanation_uses_only_linked_local_price_snapshot(tmp_path: Path, capsys) -> None:
    store = tmp_path / "store"
    store.mkdir()
    snapshot = PriceSnapshot.model_validate_json(json.dumps({
        "endpoint": "https://example.test/v1", "provider": "vendor", "model": "m",
        "currency": "USD", "tier": "standard", "cache_regime": "default",
        "source": "fixture", "source_date": "2026-09-20",
        "effective_at": "2026-09-20T00:00:00Z",
        "rates_per_million": {"inputUncached": "10", "cacheRead": "1",
                              "cacheWrite": "20", "output": "30"},
    }))
    with PriceStore(store / "prices.sqlite3") as prices:
        snapshot_id = prices.record(snapshot)["snapshotId"]
    event_id = str(uuid4())
    event = {
        "schemaVersion": 1, "eventId": event_id,
        "occurredAt": "2026-09-21T12:00:00.000Z", "sourceId": "fixture",
        "sourceEventId": event_id, "projectId": "p", "taskId": "task",
        "sessionId": "session", "requestId": "request", "attemptId": "attempt",
        "clientId": "fixture", "adapterVersion": "1", "modelId": "m",
        "providerId": "vendor", "executionLocation": "remote",
        "eventType": "usage", "evidence": "provider_reported",
        "payload": {"inputTokens": 100, "outputTokens": 10,
                    "cacheReadTokens": 0, "cacheWriteTokens": 0,
                    "complete": True, "category": "primary", "callId": "call",
                    "costUsd": None, "priceSnapshotId": snapshot_id},
    }
    with Julius(store) as julius:
        julius.record_usage(event)
    baseline = {"id": "baseline", "taskId": "task",
                "evidence": "controlled_experiment", "calls": [{
                    "callId": "baseline-call", "modelId": "m", "providerId": "vendor",
                    "occurredAt": "2026-09-21T12:00:00Z", "inputTokens": 200,
                    "cacheReadTokens": 0, "cacheWriteTokens": 0,
                    "outputTokens": 10, "priceSnapshotId": snapshot_id,
                }]}
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline))
    assert run(["savings", "--task", "task", "--explain", "--json",
                "--coverage-complete", "--baseline", str(baseline_path),
                "--since", "2026-09-21T00:00:00Z", "--until", "2026-09-22T00:00:00Z",
                "--data-dir", str(store)]) == 0
    analysis = json.loads(capsys.readouterr().out)
    assert analysis["currentModeledCostUsd"] == pytest.approx(0.0013)
    assert analysis["netModeledSavingsUsd"] == pytest.approx(0.001)


def test_price_snapshot_id_cannot_cross_model_identities(tmp_path: Path) -> None:
    events = [
        {"eventType": "usage", "providerId": "vendor", "modelId": model,
         "payload": {"priceSnapshotId": "same"}}
        for model in ("one", "two")
    ]
    with pytest.raises(ValueError, match="conflicting model identities"):
        _stored_task_prices(tmp_path, events, None)


def test_cli_serve_processes_offline_jsonl(tmp_path: Path, monkeypatch) -> None:
    request = {"protocolVersion": 1, "id": "report-1", "operation": "report", "params": {"query": {}}}
    input_stream = io.StringIO(json.dumps(request) + "\n")
    output_stream = io.StringIO()
    monkeypatch.setattr("sys.stdin", input_stream)
    monkeypatch.setattr("sys.stdout", output_stream)
    assert run(["serve", "--data-dir", str(tmp_path / "store")]) == 0
    response = json.loads(output_stream.getvalue())
    assert response["ok"] is True
    assert response["id"] == "report-1"
    assert response["result"]["financialSavingsUsd"] is None
