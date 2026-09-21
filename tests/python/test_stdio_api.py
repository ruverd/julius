"""The transport stays framed and offline across malformed requests."""

import io
import json

from julius.stdio_api import MAX_REQUEST_BYTES, serve_stdio


def invoke(tmp_path, *requests):
    incoming = io.StringIO("".join(item + "\n" for item in requests))
    outgoing = io.StringIO()
    serve_stdio(tmp_path, incoming, outgoing)
    return [json.loads(line) for line in outgoing.getvalue().splitlines()]


def request(identifier, operation, params):
    return json.dumps({"protocolVersion": 1, "id": identifier, "operation": operation, "params": params})


def test_report_and_optimize_are_offline(tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("network access")

    monkeypatch.setattr("socket.socket.connect", forbidden)
    replies = invoke(
        tmp_path,
        request("a", "report", {"query": {}}),
        request("b", "optimize", {"context": {"projectId": "p", "category": "tool_output", "content": "hello"}, "policy": {"mode": "observe", "version": "1"}}),
    )
    assert [reply["id"] for reply in replies] == ["a", "b"]
    assert all(reply["ok"] for reply in replies)
    assert replies[0]["result"]["observedCalls"] == 0
    assert replies[1]["result"]["receipt"]["applied"] is False


def test_bad_lines_are_isolated(tmp_path):
    replies = invoke(
        tmp_path,
        "{broken",
        "x" * (MAX_REQUEST_BYTES + 1),
        request("version", "report", {"query": {}}).replace('"protocolVersion": 1', '"protocolVersion": 2'),
        request("ok", "report", {"query": {}}),
    )
    assert [reply.get("error") for reply in replies[:3]] == [
        "invalid_json", "request_too_large", "unsupported_protocol_version"
    ]
    assert replies[3]["ok"] is True


def test_only_allowlisted_operations_and_exact_arguments(tmp_path):
    replies = invoke(
        tmp_path,
        request("x", "send_xai", {}),
        request("y", "recordUsage", {"event": {}, "extra": True}),
        request("z", "recordOutcome", {"event": {}}),
    )
    assert replies[0]["error"] == "unknown_operation"
    assert replies[1]["error"] == "invalid_params"
    assert replies[2]["error"].startswith("invalid_params:")
