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
        assert len(events) == 2
        transform = next(event for event in events if event["eventType"] == "transform")
        usage = next(event for event in events if event["eventType"] == "usage")
        assert transform["payload"]["scope"] == "tool_output"
        assert transform["evidence"] == "heuristic_estimate"
        assert transform["payload"]["tokenizer"] is None
        assert transform["payload"]["sent"] is result["candidateReceipts"][0]["applied"]
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
        transform = next(event for event in events if event["eventType"] == "transform")
        usage = next(event for event in events if event["eventType"] == "usage")
        assert transform["payload"]["sent"] is False
        assert usage["payload"]["costUsd"] is None


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
