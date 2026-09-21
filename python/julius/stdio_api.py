"""Bounded, versioned JSON Lines transport for the local Julius SDK."""

import json
from pathlib import Path
from typing import TextIO

from .sdk import Julius

PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_OPERATIONS = frozenset({"optimize", "recordUsage", "recordOutcome", "report"})


def _response(request_id: str | None, *, result: object = None, error: str | None = None) -> dict:
    if error is None:
        return {"protocolVersion": PROTOCOL_VERSION, "id": request_id, "ok": True, "result": result}
    return {"protocolVersion": PROTOCOL_VERSION, "id": request_id, "ok": False, "error": error}


def _dispatch(julius: Julius, request: object) -> dict:
    if not isinstance(request, dict):
        return _response(None, error="invalid_request")
    request_id = request.get("id")
    if not isinstance(request_id, str) or not request_id or len(request_id.encode("utf-8")) > 128:
        return _response(None, error="invalid_id")
    if set(request) != {"protocolVersion", "id", "operation", "params"}:
        return _response(request_id, error="invalid_request")
    if type(request["protocolVersion"]) is not int or request["protocolVersion"] != PROTOCOL_VERSION:
        return _response(request_id, error="unsupported_protocol_version")
    operation = request["operation"]
    if not isinstance(operation, str) or operation not in _OPERATIONS:
        return _response(request_id, error="unknown_operation")
    params = request["params"]
    if not isinstance(params, dict):
        return _response(request_id, error="invalid_params")
    try:
        if operation == "optimize":
            if set(params) != {"context", "policy"} or not all(
                isinstance(params[key], dict) for key in ("context", "policy")
            ):
                return _response(request_id, error="invalid_params")
            result = julius.optimize(params["context"], params["policy"])
        elif operation == "report":
            if set(params) != {"query"} or not isinstance(params["query"], dict):
                return _response(request_id, error="invalid_params")
            result = julius.report(params["query"])
        else:
            if set(params) != {"event"} or not isinstance(params["event"], dict):
                return _response(request_id, error="invalid_params")
            result = (
                julius.record_usage(params["event"])
                if operation == "recordUsage"
                else julius.record_outcome(params["event"])
            )
        return _response(request_id, result=result)
    except (ValueError, TypeError, KeyError) as exc:
        return _response(request_id, error=f"invalid_params: {exc}")


def serve_stdio(directory: str | Path, input_stream: TextIO, output_stream: TextIO) -> None:
    """Process one request per input line and emit one bounded response per line."""
    with Julius(directory) as julius:
        while True:
            line = input_stream.readline(MAX_REQUEST_BYTES + 1)
            if not line:
                break
            if len(line.encode("utf-8")) > MAX_REQUEST_BYTES or not line.endswith("\n"):
                # Consume the remainder so the next response starts at a request boundary.
                if not line.endswith("\n"):
                    while True:
                        rest = input_stream.readline(MAX_REQUEST_BYTES + 1)
                        if not rest or rest.endswith("\n"):
                            break
                response = _response(None, error="request_too_large")
            else:
                try:
                    response = _dispatch(julius, json.loads(line))
                except (ValueError, UnicodeError):
                    response = _response(None, error="invalid_json")
            encoded = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
            if len(encoded.encode("utf-8")) > MAX_RESPONSE_BYTES:
                encoded = json.dumps(_response(response["id"], error="response_too_large"))
            output_stream.write(encoded + "\n")
            output_stream.flush()
