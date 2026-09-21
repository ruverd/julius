"""Embedded caller attestations must fail closed and retain no prompt text."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import NAMESPACE_URL, uuid5
import json

import pytest

from julius.sdk import Julius


def evidence(**changes):
    base = {
        "project_id": "project", "session_id": "session", "request_id": "request",
        "attempt_id": "attempt", "client_id": "harness", "model_id": "pinned-model",
        "actual_model_id": "pinned-model", "response_id": "response",
        "before_input": "instructions\ntool definitions\na much longer original input",
        "after_input": "instructions\ntool definitions\nshort input",
        "sent_input": "instructions\ntool definitions\nshort input",
        "token_counter": len, "tokenizer_id": "fixture-tokenizer-v1",
        "complete_model_input": True, "task_id": "task",
    }
    return {**base, **changes}


def usage(**changes):
    base = {
        "schemaVersion": 1, "eventId": "usage-event", "occurredAt": "2026-09-21T12:00:00.000Z",
        "sourceId": "harness", "sourceEventId": "usage-event", "projectId": "project",
        "taskId": "task", "sessionId": "session", "requestId": "request",
        "attemptId": "attempt", "clientId": "harness", "adapterVersion": "harness-1",
        "modelId": "pinned-model", "providerId": None, "executionLocation": "unknown",
        "eventType": "usage", "evidence": "runtime_reported",
        "payload": {"inputTokens": None, "outputTokens": None, "cacheReadTokens": None,
                    "cacheWriteTokens": None, "complete": False, "category": "primary",
                    "callId": "observed-call", "costUsd": None, "observationScope": "call"},
    }
    return {**base, **changes}


def test_atomic_embedded_attempt_and_report_coverage(tmp_path):
    with Julius(tmp_path) as julius:
        first = julius.record_embedded_attempt(**evidence(), usage_event=usage())
        replay = julius.record_embedded_attempt(**evidence(), usage_event=usage())
        assert first["ledgerReceipt"]["inserted"] is True
        assert first["usageReceipt"]["inserted"] is True
        assert replay["ledgerReceipt"]["inserted"] is False
        assert replay["usageReceipt"]["inserted"] is False
        assert replay["event"]["occurredAt"] == first["event"]["occurredAt"]
        assert len(julius.ledger.events()) == 2
        report = julius.report({"by": "client"})
        assert report["observedCalls"] == 1
        assert report["incompleteCalls"] == 1
        assert report["coverage"]["transformedObservedRequests"] == 1
        assert report["coverage"]["observedRequestsWithId"] == 1
    raw = (tmp_path / "ledger.sqlite").read_bytes()
    assert b"tool definitions" not in raw


@pytest.mark.parametrize("change", [
    {"projectId": "other"}, {"taskId": "other"}, {"sessionId": "other"}, {"requestId": "other"},
    {"attemptId": "other"}, {"clientId": "other"}, {"modelId": "other"},
    {"eventId": ""}, {"eventType": "outcome"},
])
def test_atomic_attempt_rejects_bad_usage_without_partial_write(tmp_path, change):
    with Julius(tmp_path) as julius:
        with pytest.raises(ValueError):
            julius.record_embedded_attempt(**evidence(), usage_event=usage(**change))
        assert julius.ledger.events() == []


def test_atomic_attempt_rejects_missing_call_and_conflicting_replay(tmp_path):
    with Julius(tmp_path) as julius:
        with pytest.raises(ValueError, match="observationScope"):
            julius.record_embedded_attempt(**evidence(), usage_event=usage(
                payload={**usage()["payload"], "observationScope": "session_delta"}))
        assert julius.ledger.events() == []
        with pytest.raises(ValueError, match="callId"):
            julius.record_embedded_attempt(**evidence(), usage_event=usage(
                payload={**usage()["payload"], "callId": None}))
        assert julius.ledger.events() == []
        julius.record_embedded_attempt(**evidence(), usage_event=usage())
        with pytest.raises(ValueError, match="Conflicting source event"):
            julius.record_embedded_attempt(**evidence(), usage_event=usage(
                payload={**usage()["payload"], "outputTokens": 5}))
        assert len(julius.ledger.events()) == 2


def test_atomic_attempt_rolls_back_transform_on_usage_collision(tmp_path):
    with Julius(tmp_path) as julius:
        julius.record_usage(usage())
        with pytest.raises(ValueError, match="Conflicting source event"):
            julius.record_embedded_attempt(**evidence(), usage_event=usage(
                payload={**usage()["payload"], "outputTokens": 5}))
        assert len(julius.ledger.events()) == 1


def test_atomic_attempt_requires_distinct_id_and_retry_attempt(tmp_path):
    key = json.dumps(("project", "session", "request", "attempt", "harness"),
                     separators=(",", ":"), ensure_ascii=False)
    transform_id = str(uuid5(NAMESPACE_URL, "julius-embedded-request:" + key))
    with Julius(tmp_path) as julius:
        with pytest.raises(ValueError, match="IDs must differ"):
            julius.record_embedded_attempt(**evidence(), usage_event=usage(eventId=transform_id))
        assert julius.ledger.events() == []
        julius.record_embedded_attempt(**evidence(), usage_event=usage())
        retry = julius.record_embedded_attempt(
            **evidence(attempt_id="retry"),
            usage_event=usage(eventId="retry-usage", sourceEventId="retry-usage",
                              attemptId="retry", payload={**usage()["payload"],
                                                             "callId": "retry-call"}),
        )
        assert retry["ledgerReceipt"]["inserted"] is True
        assert retry["usageReceipt"]["inserted"] is True
        assert len(julius.ledger.events()) == 4


def test_atomic_attempt_first_open_concurrent_replay(tmp_path):
    barrier = Barrier(4)

    def record() -> dict:
        with Julius(tmp_path) as julius:
            barrier.wait(timeout=5)
            return julius.record_embedded_attempt(**evidence(), usage_event=usage())

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: record(), range(4)))
    assert sum(item["ledgerReceipt"]["inserted"] for item in results) == 1
    assert sum(item["usageReceipt"]["inserted"] for item in results) == 1
    assert len({item["event"]["occurredAt"] for item in results}) == 1


def test_records_sent_caller_count_and_idempotent_duplicate(tmp_path):
    with Julius(tmp_path) as julius:
        first = julius.record_embedded_request(**evidence())
        second = julius.record_embedded_request(**evidence())
        assert first["ledgerReceipt"]["inserted"] is True
        assert second["ledgerReceipt"]["inserted"] is False
        assert second["event"]["occurredAt"] == first["event"]["occurredAt"]
        assert first["event"]["evidence"] == "tokenizer_counted"
        assert first["event"]["payload"]["scope"] == "request"
        assert first["deltaTokens"] > 0
        assert first["providerMeasured"] is False
        assert len(julius.ledger.events()) == 1
        report = julius.report({"by": "client"})
        assert report["groupBy"] == "client"
        assert report["directInputReduction"][0]["tokens"]["total"] == first["deltaTokens"]
        assert report["directInputReduction"][0]["evidence"] == "tokenizer_counted"
        with pytest.raises(ValueError, match="Group"):
            julius.report({"by": "unknown"})
    raw = (tmp_path / "ledger.sqlite").read_bytes()
    assert b"instructions" not in raw
    assert b"tool definitions" not in raw
    assert b"long input" not in raw


def test_negative_reduction_preserved(tmp_path):
    expanded = "instructions\ntool definitions\n" + "expanded input " * 8
    with Julius(tmp_path) as julius:
        result = julius.record_embedded_request(**evidence(
            after_input=expanded, sent_input=expanded,
        ))
        assert result["deltaTokens"] < 0
        assert result["event"]["payload"]["inputTokens"] - result["event"]["payload"]["outputTokens"] < 0


@pytest.mark.parametrize("change", [
    {"actual_model_id": "another-model"},
    {"response_id": ""},
    {"complete_model_input": False},
    {"sent_input": "not what was counted"},
    {"token_counter": lambda _: None},
    {"token_counter": lambda _: True},
])
def test_rejects_ambiguous_or_invalid_evidence(tmp_path, change):
    with Julius(tmp_path) as julius:
        with pytest.raises(ValueError):
            julius.record_embedded_request(**evidence(**change))
        assert julius.ledger.events() == []


@pytest.mark.parametrize("change", [
    {"token_counter": lambda _: 1},
    {"response_id": "different-response"},
    {"after_input": "new content", "sent_input": "new content"},
])
def test_conflicting_retry_is_rejected(tmp_path, change):
    with Julius(tmp_path) as julius:
        julius.record_embedded_request(**evidence())
        with pytest.raises(ValueError, match="Conflicting source event"):
            julius.record_embedded_request(**evidence(**change))


def test_same_attempt_is_idempotent_across_concurrent_connections(tmp_path):
    barrier = Barrier(4)

    def record() -> dict:
        with Julius(tmp_path) as julius:
            barrier.wait(timeout=5)
            return julius.record_embedded_request(**evidence())

    with ThreadPoolExecutor(max_workers=4) as executor:
        receipts = list(executor.map(lambda _: record(), range(4)))
    assert sum(item["ledgerReceipt"]["inserted"] for item in receipts) == 1
    assert len({item["event"]["occurredAt"] for item in receipts}) == 1
    with Julius(tmp_path) as julius:
        assert len(julius.ledger.events()) == 1
