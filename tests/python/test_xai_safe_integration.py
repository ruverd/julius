"""Fixture-only xAI safe-send accounting tests."""

import json

import pytest

from julius.sdk import Julius


LINE = "ordinary repeated status line with enough detail for deterministic reduction and retrieval"
POLICY = {"mode": "safe", "version": "1.0.0", "approved": True}
TOOL = {"type": "function", "name": "julius_restore_artifact",
        "parameters": {"type": "object", "properties": {"artifact_id": {"type": "string"}},
                       "required": ["artifact_id"]}}


def request():
    return {"model": "grok-requested", "tools": [TOOL],
            "input": [{"type": "function_call_output", "call_id": "call_0",
                       "output": "\n".join([LINE] * 8)}]}


def provider_response():
    return json.dumps({"id": "resp_1", "model": "grok-actual", "status": "completed",
                       "usage": {"input_tokens": 30, "output_tokens": 3,
                                 "cost_in_usd_ticks": 100_000},
                       "output": [{"type": "message", "content": []}]}).encode()


def test_safe_send_records_transform_and_provider_attempt(tmp_path):
    calls = []

    def transport(body, headers):
        calls.append(json.loads(body))
        return provider_response()

    source = request()
    with Julius(tmp_path) as julius:
        result = julius.send_xai_optimized(
            source, api_key="fixture-key", project_id="project", session_id="session",
            policy=POLICY, transport=transport,
        )
        events = julius.ledger.events()
        assert len(calls) == len(result["attempts"]) == 1
        assert len(events) == 3
        transform = next(event for event in events if event["eventType"] == "transform" and event["payload"]["scope"] == "tool_output")
        request_transform = next(event for event in events if event["eventType"] == "transform" and event["payload"]["scope"] == "request")
        usage = next(event for event in events if event["eventType"] == "usage")
        assert transform["payload"]["scope"] == "tool_output"
        assert transform["evidence"] == "heuristic_estimate"
        assert transform["payload"]["tokenizer"] is None
        assert transform["payload"]["sent"] is result["candidateReceipts"][0]["applied"]
        assert request_transform["payload"]["inputTokens"] is None
        assert request_transform["payload"]["sent"] is True
        assert result["requestMeasurement"]["deltaBytes"] > 0
        assert result["requestMeasurement"]["tokenComparisonValid"] is False
        assert usage["payload"]["costUsd"] == pytest.approx(0.00001)
        assert julius.report()["financialSavingsUsd"] is None
        assert source["input"][0]["output"] == "\n".join([LINE] * 8)


def test_failed_send_keeps_candidate_unsent_and_usage_unknown(tmp_path):
    calls = []

    def transport(body, headers):
        calls.append(body)
        raise OSError("ambiguous failure")

    with Julius(tmp_path) as julius:
        result = julius.send_xai_optimized(
            request(), api_key="fixture-key", project_id="project", session_id="session",
            policy=POLICY, transport=transport,
        )
        events = julius.ledger.events()
        assert len(calls) == len(result["attempts"]) == 1
        assert result["complete"] is False
        transform = next(event for event in events if event["eventType"] == "transform" and event["payload"]["scope"] == "tool_output")
        request_transform = next(event for event in events if event["eventType"] == "transform" and event["payload"]["scope"] == "request")
        usage = next(event for event in events if event["eventType"] == "usage")
        assert transform["payload"]["sent"] is False
        assert request_transform["payload"]["sent"] is False
        assert usage["payload"]["costUsd"] is None


def test_safe_send_ledger_failure_returns_unreconciled_provider_attempt(tmp_path):
    calls = []

    def transport(body, headers):
        calls.append(body)
        return provider_response()

    with Julius(tmp_path) as julius:
        def fail_record(event):
            raise OSError("ledger unavailable")

        julius.record_usage = fail_record
        result = julius.send_xai_optimized(
            request(), api_key="fixture-key", project_id="project", session_id="session",
            policy=POLICY, transport=transport,
        )
        assert len(calls) == 1
        assert result["complete"] is False
        assert result["ledgerRecordingStatus"] == "unknown"
        assert result["attemptEvidence"][0]["responseId"] == "resp_1"
        assert result["attemptEvidence"][0]["inputTokens"] == 30
        assert result["requestMeasurement"]["sent"] is None
        assert result["candidateReceipts"][0]["applied"] is True
        assert result["requestTransformEvent"] is None
        assert result["transformEvents"] == []
        assert julius.ledger.events() == []


def test_completed_response_without_usage_confirms_candidate_was_sent(tmp_path):
    def transport(body, headers):
        return json.dumps({"id": "resp_without_usage", "model": "grok-actual",
                           "status": "completed", "output": []}).encode()

    with Julius(tmp_path) as julius:
        result = julius.send_xai_optimized(
            request(), api_key="fixture-key", project_id="project", session_id="session",
            policy=POLICY, transport=transport,
        )
        usage = result["attempts"][0]["usageEvent"]
        assert result["complete"] is False
        assert usage["payload"]["complete"] is False
        assert usage["payload"]["inputTokens"] is None
        assert usage["payload"]["costUsd"] is None
        assert result["requestMeasurement"]["sent"] is True
        assert result["requestTransformEvent"]["payload"]["sent"] is True
        assert result["transformEvents"][0]["event"]["payload"]["sent"] is True
        assert result["requestTransformEvent"]["executionLocation"] == "remote"
        assert result["requestMeasurement"]["tokenComparisonValid"] is False
        assert julius.report()["financialSavingsUsd"] is None


def test_http_error_does_not_confirm_candidate_was_sent(tmp_path):
    from urllib.error import HTTPError

    def transport(body, headers):
        raise HTTPError("https://api.x.ai/v1/responses", 503, "Unavailable", {}, None)

    with Julius(tmp_path) as julius:
        result = julius.send_xai_optimized(
            request(), api_key="fixture-key", project_id="project", session_id="session",
            policy=POLICY, transport=transport,
        )
        assert result["requestMeasurement"]["sent"] is False
        assert result["requestTransformEvent"]["payload"]["sent"] is False
        assert result["transformEvents"][0]["event"]["payload"]["sent"] is False
        assert result["requestTransformEvent"]["executionLocation"] == "unknown"


def test_serialized_json_counter_does_not_claim_model_input_savings(tmp_path):
    def transport(body, headers):
        return json.dumps({"id": "resp_1", "model": "grok-requested", "status": "completed",
                           "usage": {"input_tokens": 30, "output_tokens": 3},
                           "output": [{"type": "message", "content": []}]}).encode()

    with Julius(tmp_path) as julius:
        result = julius.send_xai_optimized(
            request(), api_key="fixture-key", project_id="project", session_id="session",
            policy=POLICY, transport=transport, token_counter=lambda text: len(text.split()),
            tokenizer_model_id="grok-requested", tokenizer_id="fixture-counter-v1",
        )
        event = result["requestTransformEvent"]
        assert event["payload"]["scope"] == "request"
        assert event["payload"]["sent"] is True
        assert event["evidence"] == "heuristic_estimate"
        assert event["payload"]["inputTokens"] is None
        assert event["payload"]["outputTokens"] is None
        assert result["requestMeasurement"]["beforeTokens"] is not None
        assert result["requestMeasurement"]["tokenComparisonValid"] is False
        assert result["requestMeasurement"]["tokenComparisonReason"] == "serialized_request_only"
        summary = julius.report()
        assert len(summary["directInputReduction"]) == 1
        assert len(summary["toolOutputReduction"]) == 1
        assert summary["directInputReduction"][0]["tokens"]["total"] is None
        assert summary["coverage"]["transformedObservedRequests"] == 1


def test_explicit_model_input_counter_keeps_tokenizer_provenance(tmp_path):
    def transport(body, headers):
        return json.dumps({"id": "resp_1", "model": "grok-requested", "status": "completed",
                           "usage": {"input_tokens": 30, "output_tokens": 3},
                           "output": []}).encode()

    def count_model_input(serialized_request):
        body = json.loads(serialized_request)
        return len(body["input"][0]["output"].split())

    with Julius(tmp_path) as julius:
        result = julius.send_xai_optimized(
            request(), api_key="fixture-key", project_id="project", session_id="session",
            policy=POLICY, transport=transport, token_counter=count_model_input,
            tokenizer_model_id="grok-requested", tokenizer_id="fixture-counter-v1",
            token_counting_basis="model_input",
        )
        event = result["requestTransformEvent"]
        assert event["evidence"] == "tokenizer_counted"
        assert event["payload"]["inputTokens"] > event["payload"]["outputTokens"]
        assert result["requestMeasurement"]["tokenComparisonValid"] is True
        assert result["requestMeasurement"]["tokenComparisonReason"] is None
        assert julius.report()["directInputReduction"][0]["tokens"]["total"] > 0


def test_response_model_alias_mismatch_invalidates_attested_count(tmp_path):
    with Julius(tmp_path) as julius:
        result = julius.send_xai_optimized(
            request(), api_key="fixture-key", project_id="project", session_id="session",
            policy=POLICY, transport=lambda body, headers: provider_response(),
            token_counter=lambda text: len(text.split()),
            tokenizer_model_id="grok-requested", tokenizer_id="fixture-counter-v1",
            token_counting_basis="model_input",
        )
        measurement = result["requestMeasurement"]
        assert measurement["actualModelId"] == "grok-actual"
        assert measurement["tokenComparisonValid"] is False
        assert measurement["tokenComparisonReason"] == "actual_model_mismatch"
        assert result["requestTransformEvent"]["payload"]["inputTokens"] is None
        assert julius.report()["directInputReduction"][0]["tokens"]["total"] is None


@pytest.mark.parametrize("bad_request", [
    {"model": "grok", "input": "plain text", "tools": [TOOL]},
    {**request(), "store": False},
    {**request(), "tools": []},
])
def test_unsupported_request_fails_before_send(tmp_path, bad_request):
    sent = []

    def transport(body, headers):
        sent.append(body)
        return provider_response()

    with Julius(tmp_path) as julius:
        with pytest.raises(ValueError):
            julius.send_xai_optimized(
                bad_request, api_key="fixture-key", project_id="project",
                session_id="session", policy=POLICY, transport=transport,
            )
        assert sent == []
        assert julius.ledger.events() == []


def test_invalid_key_or_limit_rejected_before_retaining_original(tmp_path):
    with Julius(tmp_path) as julius:
        with pytest.raises(ValueError, match="xAI API key"):
            julius.send_xai_optimized(
                request(), api_key="bad\nkey", project_id="project", session_id="session",
                policy=POLICY,
            )
        with pytest.raises(ValueError, match="max_calls"):
            julius.send_xai_optimized(
                request(), api_key="fixture-key", project_id="project",
                session_id="session", policy=POLICY, max_calls=0,
            )
        assert list((tmp_path / "artifacts").rglob("*.txt")) == []
