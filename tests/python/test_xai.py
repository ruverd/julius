"""Fixture-only xAI adapter tests; no live compatibility claim."""

import json

import pytest

from julius.xai import XAIAdapter


def test_full_request_preserved_and_usage_nested_details_not_added() -> None:
    request = {
        "model": "latest",
        "input": [
            {"role": "system", "content": "Do not reveal secrets"},
            {"role": "user", "content": "Explain"},
            {"type": "function_call_output", "call_id": "call_1", "output": "result"},
        ],
        "tools": [{"type": "function", "name": "lookup", "parameters": {"type": "object"}}],
        "tool_choice": "auto",
        "prompt_cache_key": "conversation-1",
    }
    sent = []

    def transport(body, headers):
        sent.append((json.loads(body), headers))
        return json.dumps({
            "id": "resp_1", "model": "grok-4.6", "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
            "usage": {"input_tokens": 125, "output_tokens": 48, "total_tokens": 173,
                      "input_tokens_details": {"cached_tokens": 98},
                      "output_tokens_details": {"reasoning_tokens": 12}},
        }).encode()

    result = XAIAdapter().send_once(request, "test-secret", transport)
    assert sent[0][0] == request
    assert sent[0][1]["Authorization"] == "Bearer test-secret"
    assert len(sent) == 1
    assert result.complete and result.actual_model == "grok-4.6"
    assert result.requested_model == "latest" and result.response_id == "resp_1"
    assert (result.input_tokens, result.output_tokens, result.total_tokens) == (125, 48, 173)
    assert (result.cached_input_tokens, result.reasoning_tokens) == (98, 12)


def test_missing_usage_is_unknown_not_zero() -> None:
    result = XAIAdapter().send_once({"model": "grok", "input": "hi"}, "key",
                                    lambda body, headers: b'{"status":"completed"}')
    assert not result.complete
    assert result.input_tokens is None and result.output_tokens is None


def test_transport_disconnect_is_incomplete_without_retry() -> None:
    calls = []

    def fail(body, headers):
        calls.append(1)
        raise OSError("secret diagnostic")

    result = XAIAdapter().send_once({"model": "grok", "input": "hi"}, "key", fail)
    assert calls == [1]
    assert not result.complete and result.raw_usage is None
    assert "secret diagnostic" not in str(result)


@pytest.mark.parametrize("candidate", [
    {"input": "hi"},
    {"model": "grok", "input": "hi", "stream": True},
    {"model": "grok", "input": "hi", "background": True},
    {"model": "grok", "input": {"role": "user"}},
])
def test_reject_unsupported_or_ambiguous_request(candidate) -> None:
    with pytest.raises(ValueError):
        XAIAdapter().prepare(candidate)


def test_default_transport_disables_proxies_and_redirects(monkeypatch) -> None:
    from julius import xai

    handlers = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self, size):
            return b'{"id":"r1","model":"grok","status":"completed","usage":{"input_tokens":1,"output_tokens":1}}'

    class FakeOpener:
        def open(self, request, timeout):
            assert request.full_url == xai.ENDPOINT
            assert timeout == xai.TIMEOUT_SECONDS
            return FakeResponse()

    def fake_build_opener(*args):
        handlers.extend(args)
        return FakeOpener()

    monkeypatch.setattr(xai, "build_opener", fake_build_opener)
    result = xai.XAIAdapter().send_once({"model": "grok", "input": "hi"}, "key")
    assert result.complete
    assert any(isinstance(handler, xai.ProxyHandler) and handler.proxies == {}
               for handler in handlers)
    assert xai._NoRedirect in handlers


@pytest.mark.parametrize("response", [
    {"id": "r1", "status": "completed", "usage": {"input_tokens": 1, "output_tokens": 2}},
    {"model": "grok", "status": "completed", "usage": {"input_tokens": 1, "output_tokens": 2}},
    {"id": "r1", "model": "grok", "status": "completed", "usage": {"input_tokens": 1}},
    {"id": "r1", "model": "grok", "status": "incomplete", "usage": {"input_tokens": 1, "output_tokens": 2}},
])
def test_missing_attribution_or_usage_remains_incomplete(response) -> None:
    result = XAIAdapter().send_once({"model": "alias", "input": "hi"}, "key",
                                    lambda body, headers: json.dumps(response).encode())
    assert not result.complete


def test_prompt_completion_usage_shape_and_provider_cost() -> None:
    response = {
        "id": "r1", "model": "grok-4.6", "status": "completed",
        "usage": {
            "prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14,
            "prompt_tokens_details": {"cached_tokens": 3},
            "completion_tokens_details": {"reasoning_tokens": 2},
            "cost_in_usd_ticks": 158500,
        },
    }
    result = XAIAdapter().send_once({"model": "latest", "input": "hi"}, "key",
                                    lambda body, headers: json.dumps(response).encode())
    assert result.complete
    assert (result.input_tokens, result.output_tokens, result.total_tokens) == (10, 4, 14)
    assert (result.cached_input_tokens, result.reasoning_tokens) == (3, 2)
    assert result.cost_ticks == 158500


@pytest.mark.parametrize("usage", [
    {"input_tokens": 10, "prompt_tokens": 11, "output_tokens": 4},
    {"input_tokens": 10, "output_tokens": 4, "completion_tokens": 5},
    {"input_tokens": 10, "output_tokens": 4,
     "input_tokens_details": {"cached_tokens": 3},
     "prompt_tokens_details": {"cached_tokens": 2}},
    {"input_tokens": 10, "output_tokens": 4,
     "output_tokens_details": {"reasoning_tokens": 2},
     "completion_tokens_details": {"reasoning_tokens": 3}},
])
def test_conflicting_aliases_are_incomplete(usage) -> None:
    response = {"id": "r1", "model": "grok", "status": "completed", "usage": usage}
    result = XAIAdapter().send_once({"model": "grok", "input": "hi"}, "key",
                                    lambda body, headers: json.dumps(response).encode())
    assert not result.complete
