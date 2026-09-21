"""Pure provider usage normalization. Counters and prices are never guessed."""

from __future__ import annotations

from typing import Any


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _count(value: Any) -> int | None:
    return value if type(value) is int and 0 <= value <= 2**53 - 1 else None


def normalize_openai_usage(raw: Any) -> dict[str, Any]:
    envelope = _object(raw)
    usage = _object(envelope.get("usage")) or envelope
    input_tokens = _count(usage.get("input_tokens", usage.get("prompt_tokens")))
    output_tokens = _count(usage.get("output_tokens", usage.get("completion_tokens")))
    details = _object(usage.get("input_tokens_details") or usage.get("prompt_tokens_details"))
    output_details = _object(
        usage.get("output_tokens_details") or usage.get("completion_tokens_details")
    )
    cached = _count(details.get("cached_tokens"))
    return {
        "provider": "openai",
        "normalizationVersion": 1,
        "inputTokens": input_tokens,
        "uncachedInputTokens": input_tokens - cached
        if input_tokens is not None and cached is not None and cached <= input_tokens
        else None,
        "outputTokens": output_tokens,
        "totalTokens": _count(usage.get("total_tokens")),
        "cacheReadTokens": cached,
        "cacheWriteTokens": None,
        "reasoningTokens": _count(output_details.get("reasoning_tokens")),
        "costUsd": None,
        "evidence": "provider_reported",
        "raw": raw,
    }


def normalize_anthropic_usage(raw: Any) -> dict[str, Any]:
    envelope = _object(raw)
    usage = _object(envelope.get("usage")) or envelope
    uncached = _count(usage.get("input_tokens"))
    read = _count(usage.get("cache_read_input_tokens"))
    write = _count(usage.get("cache_creation_input_tokens"))
    output = _count(usage.get("output_tokens"))
    input_tokens = (
        uncached + read + write
        if uncached is not None and read is not None and write is not None
        else None
    )
    if input_tokens is not None and input_tokens > 2**53 - 1:
        input_tokens = None
    total = input_tokens + output if input_tokens is not None and output is not None else None
    if total is not None and total > 2**53 - 1:
        total = None
    return {
        "provider": "anthropic",
        "normalizationVersion": 1,
        "inputTokens": input_tokens,
        "uncachedInputTokens": uncached,
        "outputTokens": output,
        "totalTokens": total,
        "cacheReadTokens": read,
        "cacheWriteTokens": write,
        "reasoningTokens": None,
        "costUsd": None,
        "evidence": "provider_reported",
        "raw": raw,
    }
