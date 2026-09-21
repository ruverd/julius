"""Optional Jev shadow decisions. The gateway can call TypeSafe when explicitly injected."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, Protocol
import json
import math
import socket
import time
from urllib import request

Action = Literal["keep", "retrieve", "compress"]
SAFE_ACTION: Action = "keep"


@dataclass(frozen=True)
class ShadowPolicy:
    enabled: bool = False
    max_cost_usd: float = 0.0
    timeout_seconds: float = 1.0
    minimum_confidence: float = 0.8


@dataclass(frozen=True)
class JevAnswer:
    """Normalized Choice answer. Score and Noul are not needed for routing."""

    choice: str
    confidence: float
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    actual_model: str | None = None


class JevTransport(Protocol):
    def post(self, body: bytes, api_key: str, timeout_seconds: float) -> bytes: ...


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class HttpsTypeSafeTransport:
    """Direct HTTPS only: no environment proxy, redirects, retries, or response overflow."""

    endpoint = "https://api.typesafe.ai/v1/systemone"

    def post(self, body: bytes, api_key: str, timeout_seconds: float) -> bytes:
        opener = request.build_opener(request.ProxyHandler({}), _NoRedirect())
        req = request.Request(
            self.endpoint,
            data=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with opener.open(req, timeout=timeout_seconds) as response:
                content = response.read(65_537)
                if len(content) > 65_536:
                    raise ValueError("TypeSafe response too large")
                return content
        except socket.timeout as error:
            raise TimeoutError("TypeSafe request timed out") from error


class TypeSafeGateway:
    """One explicit Jev Choice request; price rates supplied by caller, per million tokens."""

    def __init__(
        self,
        api_key: str,
        *,
        input_usd_per_million: float | None = None,
        output_usd_per_million: float | None = None,
        transport: JevTransport | None = None,
    ) -> None:
        if not api_key or api_key != api_key.strip() or any(character in api_key for character in "\r\n\x00"):
            raise ValueError("Valid TypeSafe API key required")
        for rate in (input_usd_per_million, output_usd_per_million):
            if rate is not None and (not math.isfinite(rate) or rate < 0):
                raise ValueError("TypeSafe price rates must be finite and nonnegative")
        self._api_key = api_key
        self._input_rate = input_usd_per_million
        self._output_rate = output_usd_per_million
        self._transport = transport or HttpsTypeSafeTransport()

    def choose(
        self, state: Mapping[str, int | float | bool | str], eligible_actions: tuple[Action, ...], timeout_seconds: float
    ) -> JevAnswer:
        minimal_state = {key: value for key, value in state.items() if key in _ALLOWED_STATE_KEYS}
        criteria = {
            "keep": "Keep original context unchanged.",
            "retrieve": "Retrieve authorized context from source.",
            "compress": "Compress eligible context while preserving protected content.",
        }
        body = json.dumps({
            "model": "jev-latest",
            "state": minimal_state,
            "questions": {"action": {
                "type": "choice",
                "instructions": "Which eligible action best preserves task quality under the given context metadata?",
                "criteria": {action: criteria[action] for action in eligible_actions},
            }},
        }, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(body) > 16_384:
            raise ValueError("TypeSafe request too large")
        payload = json.loads(self._transport.post(body, self._api_key, timeout_seconds))
        if not isinstance(payload, dict):
            raise ValueError("Invalid TypeSafe response")
        answers = payload.get("answers")
        answer = answers.get("action") if isinstance(answers, dict) else None
        if not isinstance(answer, dict):
            raise ValueError("Missing TypeSafe Choice answer")
        choice, confidence = answer.get("choice"), answer.get("confidence")
        if not isinstance(choice, str) or isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ValueError("Invalid TypeSafe Choice answer")
        usage = payload.get("usage")
        input_tokens = usage.get("input_tokens") if isinstance(usage, dict) else None
        output_tokens = usage.get("output_tokens") if isinstance(usage, dict) else None
        for count in (input_tokens, output_tokens):
            if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0):
                raise ValueError("Invalid TypeSafe usage")
        cost = None
        if (input_tokens is not None and output_tokens is not None
            and self._input_rate is not None and self._output_rate is not None):
            cost = (input_tokens * self._input_rate + output_tokens * self._output_rate) / 1_000_000
        model = payload.get("model")
        return JevAnswer(choice, float(confidence), cost, input_tokens, output_tokens, model if isinstance(model, str) else None)


class JevGateway(Protocol):
    """Injected gateway; implementation must enforce timeout and report its cost."""

    def choose(
        self, state: Mapping[str, int | float | bool | str],
        eligible_actions: tuple[Action, ...],
        timeout_seconds: float,
    ) -> JevAnswer: ...


@dataclass(frozen=True)
class ShadowReceipt:
    applied_action: Action
    proposed_action: Action | None
    reason: str
    elapsed_seconds: float
    cost_usd: float | None
    confidence: float | None
    input_tokens: int | None = None
    output_tokens: int | None = None
    actual_model: str | None = None


_ALLOWED_STATE_KEYS = frozenset(
    {"input_tokens", "estimated_reduction_tokens", "artifact_recoverable", "has_protected_content", "model_local"}
)


def shadow_decide(
    *,
    state: Mapping[str, int | float | bool | str],
    eligible_actions: tuple[Action, ...],
    policy: ShadowPolicy,
    gateway: JevGateway | None = None,
) -> ShadowReceipt:
    """Evaluate optional suggestion without changing the deterministic action.

    State uses a fixed metadata allowlist. Raw prompts, paths, IDs, and secrets never
    reach the gateway through this interface. Gateway owns transport and hard timeout.
    """

    if not policy.enabled:
        return ShadowReceipt(SAFE_ACTION, None, "disabled", 0.0, None, None)
    if gateway is None:
        return ShadowReceipt(SAFE_ACTION, None, "gateway_unavailable", 0.0, None, None)
    if not math.isfinite(policy.max_cost_usd) or policy.max_cost_usd <= 0:
        return ShadowReceipt(SAFE_ACTION, None, "budget_unavailable", 0.0, None, None)
    if not math.isfinite(policy.timeout_seconds) or policy.timeout_seconds <= 0:
        return ShadowReceipt(SAFE_ACTION, None, "invalid_timeout", 0.0, None, None)
    if any(action not in ("keep", "retrieve", "compress") for action in eligible_actions):
        return ShadowReceipt(SAFE_ACTION, None, "invalid_eligible_action", 0.0, None, None)
    if not eligible_actions:
        return ShadowReceipt(SAFE_ACTION, None, "no_eligible_action", 0.0, None, None)
    if not math.isfinite(policy.minimum_confidence) or not 0 <= policy.minimum_confidence <= 1:
        return ShadowReceipt(SAFE_ACTION, None, "invalid_confidence_threshold", 0.0, None, None)

    authorized = {key: value for key, value in state.items() if key in _ALLOWED_STATE_KEYS}
    started = time.monotonic()
    try:
        answer = gateway.choose(authorized, eligible_actions, policy.timeout_seconds)
    except TimeoutError:
        return ShadowReceipt(SAFE_ACTION, None, "timeout", time.monotonic() - started, None, None)
    except Exception:
        return ShadowReceipt(SAFE_ACTION, None, "gateway_error", time.monotonic() - started, None, None)

    elapsed = time.monotonic() - started
    cost = answer.cost_usd
    if cost is None or not math.isfinite(cost) or cost < 0:
        return ShadowReceipt(SAFE_ACTION, None, "cost_unknown", elapsed, cost, answer.confidence, answer.input_tokens, answer.output_tokens, answer.actual_model)
    if cost > policy.max_cost_usd:
        return ShadowReceipt(SAFE_ACTION, None, "budget_exceeded", elapsed, cost, answer.confidence, answer.input_tokens, answer.output_tokens, answer.actual_model)
    if elapsed > policy.timeout_seconds:
        return ShadowReceipt(SAFE_ACTION, None, "deadline_exceeded", elapsed, cost, answer.confidence, answer.input_tokens, answer.output_tokens, answer.actual_model)
    if answer.choice not in eligible_actions:
        return ShadowReceipt(SAFE_ACTION, None, "ineligible_choice", elapsed, cost, answer.confidence, answer.input_tokens, answer.output_tokens, answer.actual_model)
    if not math.isfinite(answer.confidence) or answer.confidence < policy.minimum_confidence:
        return ShadowReceipt(SAFE_ACTION, None, "low_confidence", elapsed, cost, answer.confidence, answer.input_tokens, answer.output_tokens, answer.actual_model)
    return ShadowReceipt(SAFE_ACTION, answer.choice, "shadow_only", elapsed, cost, answer.confidence, answer.input_tokens, answer.output_tokens, answer.actual_model)
