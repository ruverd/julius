"""Fixture-only SDK accounting for an explicit xAI restore continuation."""

import json

import pytest

from julius.sdk import Julius


def response(response_id, output, *, cost=100_000):
    return json.dumps({"id": response_id, "model": "grok-actual", "status": "completed",
                       "usage": {"input_tokens": 20, "output_tokens": 4,
                                 "cost_in_usd_ticks": cost}, "output": output}).encode()


def request():
    return {"model": "grok-requested", "input": [{"role": "user", "content": "Explain"}],
            "tools": [{"type": "function", "name": "julius_restore_artifact",
                       "parameters": {"type": "object", "properties": {
                           "artifact_id": {"type": "string"}}, "required": ["artifact_id"]}}]}


def test_sdk_records_each_restore_attempt_once(tmp_path):
    with Julius(tmp_path) as julius:
        artifact_id = julius.artifacts.put("project", "full original")["id"]
        calls = []

        def transport(body, headers):
            calls.append(json.loads(body))
            if len(calls) == 1:
                return response("resp_1", [{"type": "function_call",
                                            "name": "julius_restore_artifact",
                                            "call_id": "call_1",
                                            "arguments": json.dumps({"artifact_id": artifact_id})}])
            assert len(julius.ledger.events()) == 1
            return response("resp_2", [{"type": "message", "content": []}], cost=200_000)

        outcome = julius.send_xai_with_restores(
            request(), api_key="fixture-key", project_id="project", session_id="session",
            task_id="task", transport=transport,
        )
        events = julius.ledger.events()
        assert outcome["complete"] is True
        assert len(outcome["attempts"]) == len(events) == len(calls) == 2
        assert len({event["requestId"] for event in events}) == 2
        assert len({event["attemptId"] for event in events}) == 2
        assert {event["modelId"] for event in events} == {"grok-actual"}
        assert {event["payload"]["callId"]: event["payload"]["category"] for event in events} == {
            "resp_1": "primary", "resp_2": "restoration",
        }
        assert sum(event["payload"]["costUsd"] for event in events) == pytest.approx(0.00003)
        assert all(event["payload"]["costProvenance"]["chargeSource"] == "provider_usage"
                   for event in events)
        assert all(event["payload"]["complete"] for event in events)
        assert calls[1]["previous_response_id"] == "resp_1"
        assert calls[1]["input"][0]["output"] == "full original"
        assert julius.report()["financialSavingsUsd"] is None


def test_incomplete_continuation_still_records_both_attempts(tmp_path):
    with Julius(tmp_path) as julius:
        artifact_id = julius.artifacts.put("project", "full original")["id"]
        calls = []

        def transport(body, headers):
            calls.append(body)
            if len(calls) == 1:
                return response("resp_1", [{"type": "function_call",
                                            "name": "julius_restore_artifact",
                                            "call_id": "call_1",
                                            "arguments": json.dumps({"artifact_id": artifact_id})}])
            raise OSError("ambiguous transport failure")

        outcome = julius.send_xai_with_restores(
            request(), api_key="fixture-key", project_id="project", session_id="session",
            transport=transport,
        )
        events = julius.ledger.events()
        assert outcome["complete"] is False
        assert len(outcome["attempts"]) == len(events) == len(calls) == 2
        assert sorted(event["payload"]["complete"] for event in events) == [False, True]
        incomplete = next(event for event in events if not event["payload"]["complete"])
        assert incomplete["payload"]["inputTokens"] is None
        assert incomplete["payload"]["costUsd"] is None


def test_ledger_failure_retains_sent_attempt_evidence_without_continuation(tmp_path):
    with Julius(tmp_path) as julius:
        calls = []

        def transport(body, headers):
            calls.append(body)
            return response("resp_1", [{"type": "function_call", "name": "julius_restore_artifact",
                                        "call_id": "call_1", "arguments": "{}"}])

        def fail_record(event):
            raise OSError("ledger unavailable")

        julius.record_usage = fail_record
        outcome = julius.send_xai_with_restores(
            request(), api_key="fixture-key", project_id="project", session_id="session",
            transport=transport,
        )
        assert len(calls) == 1
        assert outcome["complete"] is False
        assert outcome["error"] == "Attempt callback failed"
        assert outcome["attempts"] == []
        assert outcome["ledgerRecordingStatus"] == "unknown"
        assert outcome["attemptEvidence"][0]["responseId"] == "resp_1"
        assert outcome["attemptEvidence"][0]["inputTokens"] == 20
        assert outcome["attemptEvidence"][0]["outputTokens"] == 4
        assert julius.ledger.events() == []


def test_single_send_ledger_failure_returns_provider_evidence(tmp_path):
    with Julius(tmp_path) as julius:
        calls = []

        def transport(body, headers):
            calls.append(body)
            return response("resp_1", [{"type": "message", "content": []}])

        def fail_record(event):
            raise OSError("ledger unavailable")

        julius.record_usage = fail_record
        outcome = julius.send_xai(
            request(), api_key="fixture-key", project_id="project", session_id="session",
            transport=transport,
        )
        assert len(calls) == 1
        assert outcome["complete"] is True
        assert outcome["recordingError"] == "ledger_recording_status_unknown"
        assert outcome["ledgerRecordingStatus"] == "unknown"
        assert outcome["usageEvent"] is None
        assert outcome["usageReceipt"] is None
        assert outcome["attemptEvidence"]["responseId"] == "resp_1"
        assert outcome["attemptEvidence"]["inputTokens"] == 20
        assert outcome["attemptEvidence"]["outputTokens"] == 4
        assert julius.ledger.events() == []
