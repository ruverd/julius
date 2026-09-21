from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from julius.ledger import Ledger


def usage(
    *, project: str = "project", model: str = "model", at: str = "2026-09-21T12:00:00.000Z"
) -> dict:
    event_id = str(uuid4())
    return {
        "schemaVersion": 1,
        "eventId": event_id,
        "occurredAt": at,
        "sourceId": "proxy",
        "sourceEventId": event_id,
        "projectId": project,
        "taskId": "task",
        "sessionId": "session",
        "requestId": event_id,
        "attemptId": "attempt",
        "clientId": "client",
        "adapterVersion": "1",
        "modelId": model,
        "providerId": "provider",
        "executionLocation": "remote",
        "evidence": "provider_reported",
        "eventType": "usage",
        "payload": {
            "inputTokens": 10,
            "outputTokens": 5,
            "cacheReadTokens": None,
            "cacheWriteTokens": None,
            "complete": True,
            "category": "primary",
            "callId": event_id,
            "costUsd": None,
        },
    }


def correction(target: dict, *, at: str, tokens: int) -> dict:
    event_id = str(uuid4())
    return {
        **target,
        "eventId": event_id,
        "sourceEventId": event_id,
        "occurredAt": at,
        "eventType": "reconciliation",
        "payload": {
            "targetEventId": target["eventId"],
            "effectiveInputTokens": tokens,
            "effectiveOutputTokens": 5,
            "effectiveCacheReadTokens": None,
            "effectiveCacheWriteTokens": None,
            "effectiveCostUsd": None,
            "effectiveComplete": True,
            "reason": "final counters",
        },
    }


def test_export_keeps_later_corrections_aliases_and_append_order(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "source.db")
    restored = Ledger(tmp_path / "restored.db")
    try:
        target = usage()
        excluded = usage(project="other")
        alias = {
            **target,
            "eventId": str(uuid4()),
            "sourceId": "client-log",
            "sourceEventId": "alias-1",
            "occurredAt": "2026-09-24T12:00:00.000Z",
        }
        first_correction = correction(target, at="2026-09-25T12:00:00.000Z", tokens=11)
        second_correction = correction(target, at="2026-09-26T12:00:00.000Z", tokens=12)
        excluded_correction = correction(excluded, at="2026-09-26T12:00:00.000Z", tokens=20)
        # Occurrence timestamps are deliberately different from append order.
        for event in (
            target,
            excluded,
            alias,
            first_correction,
            excluded_correction,
            second_correction,
        ):
            ledger.record(event)

        exported = ledger.export_history(
            {
                "projectId": "project",
                "taskId": "task",
                "modelId": "model",
                "since": "2026-09-21T00:00:00Z",
                "until": "2026-09-22T00:00:00Z",
            }
        )
        assert [event["eventId"] for event in exported] == [
            target["eventId"],
            first_correction["eventId"],
            second_correction["eventId"],
            alias["eventId"],
        ]
        receipts = restored.record_many(exported)
        assert receipts[-1]["duplicateOf"] == target["eventId"]
        assert restored.events()[0]["payload"]["inputTokens"] == 12
        assert restored.record(alias)["duplicateOf"] == target["eventId"]
    finally:
        restored.close()
        ledger.close()


def test_export_replays_insert_order_and_transform_ancestors(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "source.db")
    restored = Ledger(tmp_path / "restored.db")
    try:
        base = usage()
        parent = {
            **base,
            "eventType": "transform",
            "occurredAt": "2026-09-20T12:00:00.000Z",
            "payload": {
                "scope": "request",
                "inputTokens": 100,
                "outputTokens": 80,
                "tokenizer": "tokenizer",
                "transformId": "parent",
                "parentTransformId": None,
                "inputArtifactId": None,
                "outputArtifactId": None,
                "strategy": "compact",
                "sent": False,
            },
        }
        child = {
            **parent,
            "eventId": str(uuid4()),
            "sourceEventId": str(uuid4()),
            "occurredAt": "2026-09-21T12:00:00.000Z",
            "payload": {
                **parent["payload"],
                "inputTokens": 80,
                "outputTokens": 70,
                "transformId": "child",
                "parentTransformId": "parent",
            },
        }
        later_inserted = usage(at="2026-09-21T01:00:00.000Z")
        for event in (parent, child, later_inserted):
            ledger.record(event)
        exported = ledger.export_history(
            {"since": "2026-09-21T00:00:00Z", "until": "2026-09-22T00:00:00Z"}
        )
        assert [event["eventId"] for event in exported] == [
            parent["eventId"],
            child["eventId"],
            later_inserted["eventId"],
        ]
        assert all(receipt["inserted"] for receipt in restored.record_many(exported))
    finally:
        restored.close()
        ledger.close()
