from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from julius.ledger import Ledger


T0 = "2026-09-21T10:00:00.000Z"
T1 = "2026-09-21T11:00:00.000Z"
T2 = "2026-09-21T12:00:00.000Z"


def event(kind: str = "usage", **changes: object) -> dict:
    data = {
        "schemaVersion": 1, "eventId": str(uuid4()), "occurredAt": T0,
        "sourceId": "source", "sourceEventId": str(uuid4()), "projectId": "a",
        "taskId": None, "sessionId": "session", "requestId": str(uuid4()),
        "attemptId": "attempt", "clientId": "client", "adapterVersion": "1",
        "modelId": "model", "providerId": "provider", "executionLocation": "remote",
        "evidence": "provider_reported", "eventType": kind,
        "payload": {"inputTokens": 10, "outputTokens": 5, "cacheReadTokens": None,
                    "cacheWriteTokens": None, "complete": True, "category": "primary",
                    "callId": None, "costUsd": None},
    }
    data.update(changes)
    return data


def transform(base: dict, transform_id: str, parent_id: str | None, at: str) -> dict:
    return {**base, "eventId": str(uuid4()), "sourceEventId": str(uuid4()),
            "occurredAt": at, "eventType": "transform", "payload": {
                "scope": "request", "inputTokens": 10, "outputTokens": 10,
                "tokenizer": "tok", "transformId": transform_id,
                "parentTransformId": parent_id, "inputArtifactId": None,
                "outputArtifactId": None, "strategy": "compact", "sent": False}}


def correction(base: dict, at: str) -> dict:
    return {**base, "eventId": str(uuid4()), "sourceEventId": str(uuid4()),
            "occurredAt": at, "eventType": "reconciliation", "payload": {
                "targetEventId": base["eventId"], "effectiveInputTokens": 10,
                "effectiveOutputTokens": 5, "effectiveCacheReadTokens": None,
                "effectiveCacheWriteTokens": None, "effectiveCostUsd": None,
                "effectiveComplete": True, "reason": "corrected"}}


def test_delete_project_events_aliases_and_isolation(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db")
    try:
        first = event()
        first = {**first, "payload": {**first["payload"], "callId": "call"}}
        ledger.record(first)
        alias = {**first, "eventId": str(uuid4()), "sourceId": "other",
                 "sourceEventId": str(uuid4())}
        ledger.record(alias)
        other = event(projectId="b")
        ledger.record(other)
        assert ledger.delete_project_events("a") == {
            "removedEvents": 1, "removedAliases": 1}
        assert ledger.delete_project_events("a") == {
            "removedEvents": 0, "removedAliases": 0}
        assert [e["eventId"] for e in ledger.history()] == [other["eventId"]]
    finally:
        ledger.close()


def test_purge_preserves_connected_old_events_and_cutoff_boundary(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db")
    try:
        base = event()
        newer_retry = event(requestId=base["requestId"], occurredAt=T1,
                            sourceEventId=str(uuid4()), attemptId="retry")
        same_attempt = event(requestId=base["requestId"], occurredAt=T2,
                             sourceEventId=str(uuid4()), attemptId=base["attemptId"])
        independent = event()
        independent = {**independent, "payload": {**independent["payload"], "callId": "old-call"}}
        old_alias = {**independent, "eventId": str(uuid4()), "sourceId": "alias",
                     "sourceEventId": str(uuid4())}
        parent = transform(event(), "parent", None, T0)
        child = transform(parent, "child", "parent", T2)
        corrected = event()
        late_correction = correction(corrected, T2)
        other = event(projectId="b")
        for item in (base, newer_retry, same_attempt, independent, parent, child,
                     corrected, late_correction, other):
            ledger.record(item)
        ledger.record(old_alias)
        assert ledger.purge_project_events_before("a", T2) == {
            "removedEvents": 2, "removedAliases": 1,
            "retainedByDependency": 3}
        remaining = {e["eventId"] for e in ledger.history()}
        assert {base["eventId"], parent["eventId"], corrected["eventId"],
                same_attempt["eventId"], child["eventId"], late_correction["eventId"],
                other["eventId"]} == remaining
        assert ledger.purge_project_events_before("a", T2)["removedEvents"] == 0
    finally:
        ledger.close()


def test_purge_rejects_invalid_inputs_and_rolls_back_on_broken_link(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db")
    try:
        original = event()
        ledger.record(original)
        fix = correction(original, T1)
        ledger.record(fix)
        for bad in ("", " ", None, 1):
            with pytest.raises(ValueError):
                ledger.delete_project_events(bad)
            with pytest.raises(ValueError):
                ledger.purge_project_events_before(bad, T2)
        for bad in ("no date", "2026-09-21T12:00:00", None):
            with pytest.raises(ValueError):
                ledger.purge_project_events_before("a", bad)
        broken = {**fix, "payload": {**fix["payload"], "targetEventId": "missing"}}
        ledger.db.execute("UPDATE events SET body=? WHERE event_id=?",
                          (json.dumps(broken), fix["eventId"]))
        with pytest.raises(ValueError, match="Missing owned"):
            ledger.purge_project_events_before("a", T2)
        assert len(ledger.history()) == 2
    finally:
        ledger.close()
