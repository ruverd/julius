"""Explicit, single-attempt xAI Responses transport and provider usage receipt."""

from __future__ import annotations

import json
from hashlib import sha256
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

ENDPOINT = "https://api.x.ai/v1/responses"
MAX_REQUEST_BYTES = 2_000_000
MAX_RESPONSE_BYTES = 8_000_000
TIMEOUT_SECONDS = 60
Transport = Callable[[bytes, Mapping[str, str]], bytes]


@dataclass(frozen=True)
class XAIResult:
    requested_model: str
    actual_model: str | None
    response_id: str | None
    complete: bool
    input_tokens: int | None
    output_tokens: int | None
    cached_input_tokens: int | None
    reasoning_tokens: int | None
    total_tokens: int | None
    raw_usage: dict[str, Any] | None
    raw_response: dict[str, Any] | None
    error: str | None = None
    evidence: str = "provider_reported"
    cost_ticks: int | None = None
    # Identity of bytes handed to transport; delivery to the provider is unconfirmed.
    transport_body_sha256: str | None = None
    transport_body_bytes: int | None = None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


def _default_transport(body: bytes, headers: Mapping[str, str]) -> bytes:
    request = Request(ENDPOINT, body, dict(headers), method="POST")
    with build_opener(ProxyHandler({}), _NoRedirect).open(request, timeout=TIMEOUT_SECONDS) as response:
        data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("Response exceeds size limit")
    return data


def _counter(value: Any) -> int | None:
    return value if type(value) is int and 0 <= value <= 2**53 - 1 else None


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _alias_count(source: Mapping[str, Any], first: str, second: str) -> tuple[int | None, bool]:
    """Return a counter and whether present aliases disagree or are invalid."""
    present = [name for name in (first, second) if name in source]
    if not present:
        return None, False
    values = [_counter(source[name]) for name in present]
    if any(value is None for value in values) or len(set(values)) > 1:
        return None, True
    return values[0], False


def _details(
    source: Mapping[str, Any], first: str, second: str, counter_name: str
) -> tuple[dict[str, Any], bool]:
    present = [source[name] for name in (first, second) if name in source]
    if any(not isinstance(value, dict) for value in present):
        return {}, True
    if len(present) == 2:
        first_count = _counter(present[0].get(counter_name))
        second_count = _counter(present[1].get(counter_name))
        if first_count != second_count:
            return {}, True
    return present[0] if present else {}, False


class XAIAdapter:
    """Caller controls dispatch; prepare never sends or transforms request content."""

    def prepare(self, request: Mapping[str, Any]) -> bytes:
        model = _string(request.get("model"))
        if model is None:
            raise ValueError("An explicit model is required")
        if "input" not in request or not isinstance(request["input"], (str, list)):
            raise ValueError("Responses input must be a string or array")
        if request.get("stream") not in (None, False) or request.get("background") not in (None, False):
            raise ValueError("Streaming and background requests are not supported")
        try:
            body = json.dumps(request, ensure_ascii=False, separators=(",", ":"),
                              allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("Request must be JSON serializable") from exc
        if len(body) > MAX_REQUEST_BYTES:
            raise ValueError("Request exceeds size limit")
        return body

    def send_once(
        self, request: Mapping[str, Any], api_key: str, transport: Transport | None = None
    ) -> XAIResult:
        body = self.prepare(request)
        if not api_key or any(char in api_key for char in "\r\n"):
            raise ValueError("A valid dedicated xAI API key is required")
        model = str(request["model"])
        body_sha256 = sha256(body).hexdigest()
        body_bytes = len(body)
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        try:
            response_bytes = (transport or _default_transport)(body, headers)
            if len(response_bytes) > MAX_RESPONSE_BYTES:
                raise ValueError("Response exceeds size limit")
            response = json.loads(response_bytes)
        except HTTPError as exc:
            return self._incomplete(model, f"HTTP {exc.code}", body_sha256, body_bytes)
        except (URLError, TimeoutError, OSError):
            return self._incomplete(model, "Transport failed; provider usage unknown", body_sha256, body_bytes)
        except (ValueError, UnicodeError, TypeError):
            return self._incomplete(model, "Invalid or oversized provider response", body_sha256, body_bytes)
        if not isinstance(response, dict):
            return self._incomplete(model, "Invalid provider response", body_sha256, body_bytes)
        usage = response.get("usage")
        usage = usage if isinstance(usage, dict) else None
        usage_fields = usage or {}
        input_tokens, input_conflict = _alias_count(
            usage_fields, "input_tokens", "prompt_tokens"
        )
        output_tokens, output_conflict = _alias_count(
            usage_fields, "output_tokens", "completion_tokens"
        )
        input_details, input_details_conflict = _details(
            usage_fields, "input_tokens_details", "prompt_tokens_details", "cached_tokens"
        )
        output_details, output_details_conflict = _details(
            usage_fields, "output_tokens_details", "completion_tokens_details", "reasoning_tokens"
        )
        actual_model = _string(response.get("model"))
        response_id = _string(response.get("id"))
        complete = (
            response.get("status") == "completed"
            and usage is not None
            and actual_model is not None
            and response_id is not None
            and input_tokens is not None
            and output_tokens is not None
            and not input_conflict
            and not output_conflict
            and not input_details_conflict
            and not output_details_conflict
        )
        return XAIResult(
            requested_model=model,
            actual_model=actual_model,
            response_id=response_id,
            complete=complete,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=_counter(input_details.get("cached_tokens")),
            reasoning_tokens=_counter(output_details.get("reasoning_tokens")),
            total_tokens=_counter(usage.get("total_tokens")) if usage else None,
            raw_usage=usage,
            raw_response=response,
            error=None if complete else "Response incomplete or usage unavailable",
            cost_ticks=_counter(usage_fields.get("cost_in_usd_ticks")),
            transport_body_sha256=body_sha256,
            transport_body_bytes=body_bytes,
        )

    @staticmethod
    def _incomplete(model: str, error: str, body_sha256: str, body_bytes: int) -> XAIResult:
        return XAIResult(model, None, None, False, None, None, None, None, None,
                         None, None, error, transport_body_sha256=body_sha256,
                         transport_body_bytes=body_bytes)
