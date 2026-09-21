import json

from julius.artifacts import ArtifactStore
from julius.xai_tool_loop import run_restore_loop


def response(response_id, output):
    return json.dumps({"id": response_id, "model": "grok-4.6", "status": "completed",
                       "usage": {"input_tokens": 10, "output_tokens": 5},
                       "output": output}).encode()


def initial_request():
    return {"model": "grok-4.6", "input": [{"role": "user", "content": "Explain"}],
            "tools": [{"type": "function", "name": "julius_restore_artifact",
                       "parameters": {"type": "object",
                                      "properties": {"artifact_id": {"type": "string"}},
                                      "required": ["artifact_id"]}}], "store": True}


def test_restores_and_continues_once_with_same_contract(tmp_path):
    store = ArtifactStore(tmp_path)
    artifact_id = store.put("p", "secret original text")["id"]
    sent = []

    def transport(body, headers):
        sent.append((json.loads(body), dict(headers)))
        if len(sent) == 1:
            return response("resp_1", [{"type": "function_call", "name": "julius_restore_artifact",
                                        "call_id": "call_1",
                                        "arguments": json.dumps({"artifact_id": artifact_id})}])
        return response("resp_2", [{"type": "message", "content": [{"type": "output_text",
                                                                  "text": "done"}]}])

    request = initial_request()
    result = run_restore_loop(request, api_key="key", project_id="p", artifacts=store,
                              transport=transport)
    assert result.completed and result.error is None
    assert len(result.attempts) == 2
    assert result.restored_artifact_ids == (artifact_id,)
    assert sent[0][0] == request
    assert sent[1][0]["input"] == [{"type": "function_call_output", "call_id": "call_1",
                                   "output": "secret original text"}]
    assert sent[1][0]["previous_response_id"] == "resp_1"
    assert sent[1][0]["model"] == request["model"]
    assert sent[1][0]["tools"] == request["tools"]
    assert sent[0][1] == sent[1][1]
    assert "previous_response_id" not in request


def test_unknown_artifact_stops_without_continuation(tmp_path):
    calls = []

    def transport(body, headers):
        calls.append(body)
        return response("resp_1", [{"type": "function_call", "name": "julius_restore_artifact",
                                    "call_id": "call_1",
                                    "arguments": '{"artifact_id":"12345678-1234-1234-1234-123456789abc"}'}])

    result = run_restore_loop(initial_request(), api_key="key", project_id="p",
                              artifacts=ArtifactStore(tmp_path), transport=transport)
    assert not result.completed and result.error == "Original unavailable"
    assert len(calls) == len(result.attempts) == 1


def test_rejects_other_tool_and_malformed_arguments(tmp_path):
    for name, arguments, expected in (("other", "{}", "Non-Julius function call"),
                                      ("julius_restore_artifact", "{", "Malformed restore arguments")):
        calls = []

        def transport(body, headers):
            calls.append(body)
            return response("resp_1", [{"type": "function_call", "name": name,
                                        "call_id": "call_1", "arguments": arguments}])

        result = run_restore_loop(initial_request(), api_key="key", project_id="p",
                                  artifacts=ArtifactStore(tmp_path), transport=transport)
        assert result.error == expected
        assert len(calls) == 1


def test_limit_and_transport_failure_never_retry(tmp_path):
    calls = []

    def transport(body, headers):
        calls.append(body)
        return response("resp_1", [
            {"type": "function_call", "name": "julius_restore_artifact",
             "call_id": "call_1", "arguments": "{}"},
            {"type": "function_call", "name": "julius_restore_artifact",
             "call_id": "call_2", "arguments": "{}"},
        ])

    result = run_restore_loop(initial_request(), api_key="key", project_id="p",
                              artifacts=ArtifactStore(tmp_path), transport=transport,
                              max_calls=1)
    assert result.error == "Restore call limit exceeded"
    assert len(calls) == 1

    def broken_transport(body, headers):
        calls.append(body)
        raise OSError("ambiguous send failure")

    result = run_restore_loop(initial_request(), api_key="key", project_id="p",
                              artifacts=ArtifactStore(tmp_path), transport=broken_transport)
    assert not result.completed
    assert len(result.attempts) == 1
    assert len(calls) == 2


def test_unverified_state_or_missing_recovery_tool_never_sends(tmp_path):
    import pytest

    sent = []
    store = ArtifactStore(tmp_path)

    def transport(body, headers):
        sent.append(body)
        return response("unexpected", [])

    state_disabled = initial_request()
    state_disabled["store"] = False
    with pytest.raises(ValueError, match="store=false"):
        run_restore_loop(state_disabled, api_key="key", project_id="p", artifacts=store,
                         transport=transport)
    missing_tool = initial_request()
    missing_tool["tools"] = []
    with pytest.raises(ValueError, match="restore function"):
        run_restore_loop(missing_tool, api_key="key", project_id="p", artifacts=store,
                         transport=transport)
    assert sent == []
