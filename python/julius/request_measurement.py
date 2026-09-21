"""Offline whole-request measurements for serialized xAI Responses candidates."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .xai import XAIAdapter


TokenCounter = Callable[[str], int]


def measure_request_pair(
    original: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    token_counter: TokenCounter | None = None,
    model_id: str | None = None,
    tokenizer_id: str | None = None,
) -> dict[str, Any]:
    """Count full serialized bodies; token counts require an explicit pinned counter."""
    if original.get("model") != candidate.get("model"):
        raise ValueError("Whole-request model changed")
    if token_counter is not None:
        if (not isinstance(model_id, str) or not model_id
                or model_id != original.get("model")
                or not isinstance(tokenizer_id, str) or not tokenizer_id):
            raise ValueError("Counter requires matching model and tokenizer IDs")
    elif model_id is not None or tokenizer_id is not None:
        raise ValueError("Model/tokenizer IDs require a token counter")
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
        "tokenEvidence": "tokenizer_counted" if token_counter is not None else None,
        "providerMeasured": False,
        "sent": False,
    }
