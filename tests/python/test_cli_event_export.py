"""Explicit local audit export retains history without exposing raw usage by default."""

import json
from uuid import uuid4

import pytest

from julius.cli import run
from julius.sdk import Julius


def test_events_jsonl_exports_replayable_history_and_redacts_raw_usage(tmp_path, capsys) -> None:
    store = tmp_path / "store"
    event_id = str(uuid4())
    source_event_id = str(uuid4())
    usage = {
        "schemaVersion": 1, "eventId": event_id,
        "occurredAt": "2026-09-21T12:00:00.000Z",
        "sourceId": "proxy", "sourceEventId": source_event_id,
        "projectId": "p", "taskId": "task", "sessionId": "session",
        "requestId": "request", "attemptId": "attempt", "clientId": "client",
        "adapterVersion": "1", "modelId": "m", "providerId": "vendor",
        "executionLocation": "remote", "eventType": "usage",
        "evidence": "provider_reported",
        "payload": {"inputTokens": 10, "outputTokens": 2,
                    "cacheReadTokens": 0, "cacheWriteTokens": 0,
                    "complete": False, "category": "primary", "callId": "call",
                    "costUsd": None, "rawUsage": {"privateText": "do-not-export"}},
    }
    correction = {
        **usage, "eventId": str(uuid4()), "sourceEventId": "correction",
        "occurredAt": "2026-09-22T12:00:00.000Z",
        "eventType": "reconciliation",
        "payload": {"targetEventId": event_id,
                    "effectiveInputTokens": 11, "effectiveOutputTokens": 3,
                    "effectiveCacheReadTokens": 0, "effectiveCacheWriteTokens": 0,
                    "effectiveCostUsd": None, "effectiveComplete": True,
                    "reason": "final counters"},
    }
    alias = {**usage, "eventId": str(uuid4()), "sourceId": "log", "sourceEventId": "alias"}
    with Julius(store) as julius:
        julius.ledger.record(usage)
        julius.ledger.record(correction)
        julius.ledger.record(alias)

    common = ["export", "--format", "events-jsonl", "--project", "p",
              "--since", "2026-09-21T00:00:00Z",
              "--until", "2026-09-22T00:00:00Z", "--data-dir", str(store)]
    assert run(common) == 0
    exported = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [item["eventType"] for item in exported] == ["usage", "reconciliation", "usage"]
    assert exported[0]["payload"]["rawUsage"] is None
    assert exported[2]["payload"]["rawUsage"] is None
    with Julius(tmp_path / "replayed") as replayed:
        receipts = replayed.ledger.record_many(exported)
        assert sum(receipt["inserted"] for receipt in receipts) == 2
        assert replayed.ledger.events()[0]["payload"]["inputTokens"] == 11

    assert run([*common, "--include-raw"]) == 0
    raw = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert raw[0]["payload"]["rawUsage"] == {"privateText": "do-not-export"}
    with pytest.raises(ValueError, match="requires export --format events-jsonl"):
        run(["export", "--format", "csv", "--include-raw", "--data-dir", str(store)])
