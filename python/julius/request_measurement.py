"""Offline whole-request measurements for serialized xAI Responses candidates."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Literal

from .xai import XAIAdapter


TokenCounter = Callable[[str], int]
TokenCountingBasis = Literal["serialized_request", "model_input"]


def measure_request_pair(
    original: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    token_counter: TokenCounter | None = None,
    model_id: str | None = None,
    tokenizer_id: str | None = None,
    token_counting_basis: TokenCountingBasis = "serialized_request",
) -> dict[str, Any]:
    """Count serialized bodies; model-input claims require a separate attestation."""
    if token_counting_basis not in ("serialized_request", "model_input"):
        raise ValueError("Unknown token counting basis")
    if original.get("model") != candidate.get("model"):
        raise ValueError("Whole-request model changed")
    if token_counter is not None:
        if (not isinstance(model_id, str) or not model_id
                or model_id != original.get("model")
                or not isinstance(tokenizer_id, str) or not tokenizer_id):
            raise ValueError("Counter requires matching model and tokenizer IDs")
    elif model_id is not None or tokenizer_id is not None:
        raise ValueError("Model/tokenizer IDs require a token counter")
    elif token_counting_basis != "serialized_request":
        raise ValueError("Model-input basis requires a token counter")
    adapter = XAIAdapter()
    before = adapter.prepare(original)
    after = adapter.prepare(candidate)
    before_tokens: int | None = None
    after_tokens: int | None = None
    if token_counter is not None:
        counts = (token_counter(before.decode("utf-8")),
                  token_counter(after.decode("utf-8")))
        if any(type(value) is not int or value < 0 or value > 2**53 - 1 for value in counts):
            raise ValueError("Token counter returned an invalid count")
        before_tokens, after_tokens = counts
    return {
        "scope": "request",
        "beforeBytes": len(before),
        "afterBytes": len(after),
        "deltaBytes": len(before) - len(after),
        "beforeTokens": before_tokens,
        "afterTokens": after_tokens,
        "deltaTokens": (before_tokens - after_tokens
                        if before_tokens is not None and after_tokens is not None else None),
        "modelId": model_id,
        "tokenizerId": tokenizer_id,
        "tokenCountingBasis": token_counting_basis if token_counter is not None else None,
        "tokenEvidence": "tokenizer_counted" if token_counter is not None else None,
        "providerMeasured": False,
        "sent": False,
    }
