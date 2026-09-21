from __future__ import annotations

import multiprocessing as mp
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from julius.events import validate_event
from julius.ledger import Ledger


def stamp(seconds: int = 0) -> str:
    return (
        (datetime.now(timezone.utc) + timedelta(seconds=seconds))
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def usage(**overrides: object) -> dict:
    event = {
        "schemaVersion": 1,
        "eventId": str(uuid4()),
        "occurredAt": "2026-09-21T12:00:00.000Z",
        "sourceId": "proxy",
        "sourceEventId": str(uuid4()),
        "projectId": "project",
        "taskId": None,
        "sessionId": "session",
        "requestId": "request",
        "attemptId": "attempt-1",
        "clientId": "client",
        "adapterVersion": "1",
        "modelId": "model",
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
            "callId": "call",
            "costUsd": None,
        },
    }
    event.update(overrides)
    return event


def test_strict_envelope_rejects_bool_counter_and_unknown_cost() -> None:
    good = usage()
    assert validate_event(good)["payload"]["inputTokens"] == 10
    with pytest.raises(ValueError):
        validate_event({**good, "payload": {**good["payload"], "inputTokens": True}})
    with pytest.raises(ValueError):
        validate_event({**good, "modelId": None, "payload": {**good["payload"], "costUsd": 1}})
    with pytest.raises(ValueError):
        validate_event({**good, "occurredAt": "2026-09-21T12:00:00Z"})


def test_source_aliases_project_identity_and_retry(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db")
    try:
        first = usage()
        assert ledger.record(first)["inserted"]
        assert not ledger.record(first)["inserted"]
        with pytest.raises(ValueError, match="Conflicting source"):
            ledger.record({**first, "payload": {**first["payload"], "inputTokens": 11}})
        alias = {**first, "eventId": str(uuid4()), "sourceId": "log", "sourceEventId": "log-1"}
        assert ledger.record(alias)["duplicateOf"] == first["eventId"]
        with pytest.raises(ValueError, match="Conflicting source"):
            ledger.record({**alias, "projectId": "other"})
        retry = {
            **alias,
            "eventId": str(uuid4()),
            "sourceEventId": "log-2",
            "attemptId": "attempt-2",
        }
        assert ledger.record(retry)["inserted"]
        across_project = {
            **alias,
            "eventId": str(uuid4()),
            "sourceEventId": "log-3",
            "projectId": "other",
        }
        assert ledger.record(across_project)["inserted"]
        assert len(ledger.events()) == 3
    finally:
        ledger.close()


def test_reconciliation_replaces_cost_evidence_and_is_project_owned(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db")
    try:
        original = usage(
            payload={
                **usage()["payload"],
                "costUsd": 1.0,
                "costProvenance": {
                    "priceSource": "old",
                    "priceDate": "2026-09-21",
                    "priceModelId": "model",
                },
            }
        )
        ledger.record(original)
        correction = {
            **original,
            "eventId": str(uuid4()),
            "sourceEventId": "correction",
            "eventType": "reconciliation",
            "payload": {
                "targetEventId": original["eventId"],
                "effectiveInputTokens": 12,
                "effectiveOutputTokens": 6,
                "effectiveCacheReadTokens": None,
                "effectiveCacheWriteTokens": None,
                "effectiveCostUsd": 2.0,
                "effectiveCostProvenance": {
                    "priceSource": "new",
                    "priceDate": "2026-09-22",
                    "priceModelId": "model",
                },
                "effectiveComplete": True,
                "reason": "final invoice",
            },
        }
        with pytest.raises(ValueError, match="owned"):
            ledger.record({**correction, "projectId": "other"})
        ledger.record(correction)
        assert {event["eventType"] for event in ledger.history()} == {"usage", "reconciliation"}
        assert ledger.events()[0]["payload"]["costUsd"] == 2.0
        assert ledger.events()[0]["payload"]["costProvenance"]["priceSource"] == "new"
    finally:
        ledger.close()


def test_transform_chain_and_negative_delta(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db")
    try:
        base = usage()
        payload = {
            "scope": "request",
            "inputTokens": 10000,
            "outputTokens": 4000,
            "tokenizer": "tokenizer",
            "transformId": "one",
            "parentTransformId": None,
            "inputArtifactId": None,
            "outputArtifactId": None,
            "strategy": "compact",
            "sent": True,
        }
        first = {**base, "eventType": "transform", "payload": payload}
        second = {
            **first,
            "eventId": str(uuid4()),
            "sourceEventId": "second",
            "payload": {
                **payload,
                "inputTokens": 4000,
                "outputTokens": 3000,
                "transformId": "two",
                "parentTransformId": "one",
            },
        }
        ledger.record(first)
        ledger.record(second)
        with pytest.raises(ValueError, match="chain mismatch"):
            ledger.record(
                {
                    **second,
                    "eventId": str(uuid4()),
                    "sourceEventId": "bad",
                    "payload": {**second["payload"], "inputTokens": 5000, "transformId": "three"},
                }
            )
        negative = {
            **first,
            "eventId": str(uuid4()),
            "sourceEventId": "negative",
            "payload": {
                **payload,
                "transformId": "four",
                "inputTokens": 100,
                "outputTokens": 120,
                "sent": False,
            },
        }
        assert ledger.record(negative)["inserted"]
    finally:
        ledger.close()


def _reserve_worker(path: str, name: str, queue: mp.Queue) -> None:
    ledger = Ledger(path)
    try:
        queue.put(
            ledger.reserve_budget(
                {
                    "budgetId": "shared",
                    "reservationId": name,
                    "amount": 30,
                    "limit": 100,
                    "expiresAt": stamp(60),
                }
            )
        )
    finally:
        ledger.close()


def test_multiprocess_budget_cap_and_crash_expiry(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    Ledger(path).close()
    queue: mp.Queue = mp.Queue()
    workers = [
        mp.Process(target=_reserve_worker, args=(str(path), str(i), queue)) for i in range(8)
    ]
    for worker in workers:
        worker.start()
    results = [queue.get(timeout=10) for _ in workers]
    for worker in workers:
        worker.join(timeout=10)
        assert worker.exitcode == 0
    assert results.count(True) == 3
    ledger = Ledger(path)
    try:
        with pytest.raises(ValueError, match="budget limit"):
            ledger.reserve_budget(
                {
                    "budgetId": "shared",
                    "reservationId": "bypass",
                    "amount": 80,
                    "limit": 1000,
                    "expiresAt": stamp(60),
                }
            )
        assert ledger.reserve_budget(
            {
                "budgetId": "expiry",
                "reservationId": "crashed",
                "amount": 80,
                "limit": 100,
                "expiresAt": stamp(1),
            }
        )
    finally:
        ledger.close()
    time.sleep(1.1)
    ledger = Ledger(path)
    try:
        assert ledger.reserve_budget(
            {
                "budgetId": "expiry",
                "reservationId": "recovered",
                "amount": 80,
                "limit": 100,
                "expiresAt": stamp(60),
            }
        )
    finally:
        ledger.close()
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_query_windows_and_symlink_guard(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "ledger.db"
    ledger = Ledger(path)
    try:
        event = usage()
        ledger.record(event)
        assert len(ledger.history({"since": "2026-09-21T12:00:00Z"})) == 1
        assert ledger.history({"until": "2026-09-21T12:00:00Z"}) == []
        with pytest.raises(ValueError):
            ledger.history({"since": "invalid"})
    finally:
        ledger.close()
    link = tmp_path / "link.db"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="Unsafe ledger path"):
        Ledger(link)
    parent_link = tmp_path / "parent-link"
    parent_link.symlink_to(path.parent)
    with pytest.raises(ValueError, match="Unsafe ledger parent"):
        Ledger(parent_link / "other.db")


def test_incomplete_stream_correction_and_cost_requirements(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db")
    try:
        event = usage(payload={**usage()["payload"], "outputTokens": None, "complete": False})
        ledger.record(event)
        correction = {
            **event,
            "eventId": str(uuid4()),
            "sourceEventId": "final",
            "eventType": "reconciliation",
            "payload": {
                "targetEventId": event["eventId"],
                "effectiveInputTokens": 10,
                "effectiveOutputTokens": 7,
                "effectiveCacheReadTokens": None,
                "effectiveCacheWriteTokens": None,
                "effectiveCostUsd": None,
                "effectiveComplete": True,
                "reason": "final counters",
            },
        }
        ledger.record(correction)
        assert ledger.events()[0]["payload"]["complete"] is True
        assert ledger.events()[0]["payload"]["outputTokens"] == 7
        with pytest.raises(ValueError):
            validate_event(
                {**correction, "payload": {**correction["payload"], "effectiveCostUsd": 1.0}}
            )
    finally:
        ledger.close()


def test_past_reservation_is_denied_without_spend(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db")
    try:
        assert not ledger.reserve_budget(
            {
                "budgetId": "past",
                "reservationId": "expired",
                "amount": 80,
                "limit": 100,
                "expiresAt": stamp(-1),
            }
        )
        assert ledger.reserve_budget(
            {
                "budgetId": "past",
                "reservationId": "live",
                "amount": 100,
                "limit": 100,
                "expiresAt": stamp(60),
            }
        )
    finally:
        ledger.close()


def test_legacy_typescript_body_is_idempotent_and_readable(tmp_path: Path) -> None:
    import json
    import sqlite3

    path = tmp_path / "ledger.db"
    Ledger(path).close()
    legacy = usage()
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                legacy["eventId"],
                legacy["sourceId"],
                legacy["sourceEventId"],
                legacy["projectId"],
                legacy["taskId"],
                legacy["modelId"],
                legacy["eventType"],
                legacy["occurredAt"],
                legacy["payload"]["callId"],
                json.dumps(legacy, separators=(",", ":")),
            ),
        )
    ledger = Ledger(path)
    try:
        assert ledger.record(legacy)["inserted"] is False
        assert ledger.history()[0]["payload"]["observationScope"] is None
        correction = {
            **legacy,
            "eventId": str(uuid4()),
            "sourceEventId": "legacy-correction",
            "eventType": "reconciliation",
            "payload": {
                "targetEventId": legacy["eventId"],
                "effectiveInputTokens": 12,
                "effectiveOutputTokens": 6,
                "effectiveCacheReadTokens": None,
                "effectiveCacheWriteTokens": None,
                "effectiveCostUsd": None,
                "reason": "corrected",
            },
        }
        ledger.record(correction)
        assert ledger.events()[0]["payload"]["inputTokens"] == 12
        assert ledger.events()[0]["payload"]["complete"] is True
        assert ledger.events()[0]["payload"]["costProvenance"] is None
    finally:
        ledger.close()


def test_safe_integer_and_reconciliation_identity() -> None:
    base = usage()
    with pytest.raises(ValueError):
        validate_event({**base, "payload": {**base["payload"], "inputTokens": 9007199254740992}})
    with pytest.raises(ValueError):
        validate_event({**base, "payload": {**base["payload"], "inputTokens": False}})
    provenance = {"priceSource": "price", "priceDate": "2026-09-21", "priceModelId": "other"}
    with pytest.raises(ValueError, match="Price model"):
        validate_event(
            {**base, "payload": {**base["payload"], "costUsd": 1.0, "costProvenance": provenance}}
        )


def test_reconciliation_cannot_cross_session_provider_or_model(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db")
    try:
        first = usage()
        ledger.record(first)
        payload = {
            "targetEventId": first["eventId"],
            "effectiveInputTokens": 12,
            "effectiveOutputTokens": 5,
            "effectiveCacheReadTokens": None,
            "effectiveCacheWriteTokens": None,
            "effectiveCostUsd": None,
            "reason": "fix",
        }
        for key, value in (("sessionId", "other"), ("providerId", "other"), ("modelId", "other")):
            correction = {
                **first,
                "eventId": str(uuid4()),
                "sourceEventId": str(uuid4()),
                "eventType": "reconciliation",
                "payload": payload,
                key: value,
            }
            with pytest.raises(ValueError, match="owned"):
                ledger.record(correction)
    finally:
        ledger.close()


def test_record_many_rolls_back_earlier_events_and_aliases(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db")
    try:
        original = usage()
        ledger.record(original)
        alias = {**original, "eventId": str(uuid4()), "sourceId": "log", "sourceEventId": "alias"}
        new = {**original, "eventId": str(uuid4()), "sourceEventId": "new", "attemptId": "retry"}
        conflict = {
            **original,
            "eventId": str(uuid4()),
            "payload": {**original["payload"], "inputTokens": 11},
        }
        with pytest.raises(ValueError, match="Conflicting source"):
            ledger.record_many([alias, new, conflict])
        assert [event["eventId"] for event in ledger.events()] == [original["eventId"]]
        assert ledger.db.execute("SELECT count(*) FROM event_aliases").fetchone()[0] == 0
        receipts = ledger.record_many([alias, new])
        assert [receipt["inserted"] for receipt in receipts] == [False, True]
        assert len(ledger.events()) == 2
    finally:
        ledger.close()


def test_record_many_validation_failure_writes_nothing(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db")
    try:
        first = usage()
        invalid = {**usage(), "payload": {**usage()["payload"], "inputTokens": True}}
        with pytest.raises(ValueError):
            ledger.record_many([first, invalid])
        assert ledger.history() == []
    finally:
        ledger.close()


def test_call_alias_requires_equal_identity_and_measurements(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db")
    try:
        original = usage()
        ledger.record(original)
        alias = {**original, "eventId": str(uuid4()), "sourceId": "log", "sourceEventId": "alias"}
        assert ledger.record(alias)["duplicateOf"] == original["eventId"]
        variants = [
            {"payload": {**original["payload"], "inputTokens": 11}},
            {"payload": {**original["payload"], "complete": False}},
            {"modelId": "different-model"},
            {"sessionId": "different-session"},
        ]
        for index, change in enumerate(variants):
            candidate = {
                **original,
                "eventId": str(uuid4()),
                "sourceId": "log",
                "sourceEventId": f"conflict-{index}",
                **change,
            }
            with pytest.raises(ValueError, match="reconciliation required"):
                ledger.record(candidate)
        assert len(ledger.events()) == 1
        assert ledger.db.execute("SELECT count(*) FROM event_aliases").fetchone()[0] == 1
        retry = {
            **original,
            "eventId": str(uuid4()),
            "sourceEventId": "retry",
            "attemptId": "attempt-2",
        }
        assert ledger.record(retry)["inserted"] is True
        assert len(ledger.events()) == 2
    finally:
        ledger.close()
