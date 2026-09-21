"""Embedded caller attestations must fail closed and retain no prompt text."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

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
