"""Explicit JSONL imports. No filesystem scanning or model execution."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from .adapters import normalize_anthropic_usage
from .events import validate_event


def _obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _count(value: Any) -> int | None:
    return value if type(value) is int and 0 <= value <= 2**53 - 1 else None


def _time(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return (
            parsed.astimezone(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
    except ValueError:
        return None


def _rows(text: str) -> list[dict[str, Any]]:
    result = []
    for index, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("not an object")
            result.append(value)
        except (ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"Invalid JSONL line {index}: {error}") from error
    return result


def _base(
    options: dict[str, str],
    session: str,
    source_event: str,
    time: str,
    client: str,
    request: str | None,
    model: str | None,
) -> dict[str, Any]:
    project, source = options.get("projectId"), options.get("sourceId")
    if not _string(project) or not _string(source):
        raise ValueError("projectId and sourceId are required")
    event_id = hashlib.sha256(
        json.dumps([project, source, source_event], separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schemaVersion": 1,
        "eventId": event_id,
        "occurredAt": time,
        "sourceId": source,
        "sourceEventId": source_event,
        "projectId": project,
        "taskId": None,
        "sessionId": session,
        "requestId": request,
        "attemptId": None,
        "clientId": client,
        "adapterVersion": "experimental-jsonl-1",
        "modelId": model,
        "providerId": "anthropic" if client == "claude" else "openai",
        "executionLocation": "unknown",
        "evidence": "provider_reported",
        "eventType": "usage",
    }


def import_claude_transcript(text: str, options: dict[str, str]) -> list[dict[str, Any]]:
    selected: dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, Any], str, str, str]] = {}
    for row in _rows(text):
        if row.get("type") != "assistant":
            continue
        message = _obj(row.get("message"))
        usage = _obj(message.get("usage"))
        message_id, time = _string(message.get("id")), _time(row.get("timestamp"))
        if not usage or not message_id or not time:
            continue
        session = _string(row.get("sessionId")) or options.get("sourceId", "")
        key = f"{session}:{message_id}"
        if key not in selected or time >= selected[key][5]:
            selected[key] = row, message, usage, session, message_id, time
    result = []
    for row, message, usage, session, message_id, time in selected.values():
        normalized = normalize_anthropic_usage(usage)
        event = _base(
            options,
            session,
            f"{session}:message:{message_id}",
            time,
            "claude",
            _string(row.get("requestId")) or message_id,
            _string(message.get("model")),
        )
        event["payload"] = {
            "inputTokens": normalized["inputTokens"],
            "outputTokens": normalized["outputTokens"],
            "cacheReadTokens": normalized["cacheReadTokens"],
            "cacheWriteTokens": normalized["cacheWriteTokens"],
            "complete": _string(message.get("stop_reason")) is not None,
            "category": "primary",
            "callId": f"{session}:{message_id}",
            "costUsd": None,
            "observationScope": "call",
            "rawUsage": usage,
            "normalizerVersion": "anthropic-1",
        }
        result.append(validate_event(event))
    return result


def _counters(value: Any) -> tuple[int, int, int | None, int | None] | None:
    usage = _obj(value)
    input_tokens, output = _count(usage.get("input_tokens")), _count(usage.get("output_tokens"))
    return (
        (
            input_tokens,
            output,
            _count(usage.get("cached_input_tokens")),
            _count(usage.get("cache_write_input_tokens")),
        )
        if input_tokens is not None and output is not None
        else None
    )


def import_codex_rollout(text: str, options: dict[str, str]) -> list[dict[str, Any]]:
    session = options.get("sourceId", "")
    previous: tuple[int, int, int | None, int | None] = (0, 0, 0, 0)
    has_session_start = has_baseline = False
    result = []
    for index, row in enumerate(_rows(text)):
        payload = _obj(row.get("payload"))
        if row.get("type") == "session_meta":
            session = _string(payload.get("id")) or session
            previous, has_baseline, has_session_start = (0, 0, 0, 0), False, True
            continue
        if row.get("type") != "event_msg" or payload.get("type") != "token_count":
            continue
        raw = _obj(_obj(payload.get("info")).get("total_token_usage"))
        current, time = _counters(raw), _time(row.get("timestamp"))
        if current is None or time is None:
            continue
        if not has_baseline:
            has_baseline = True
            if not has_session_start:
                previous = current
                continue
        if any(c is not None and p is not None and c < p for c, p in zip(current, previous)):
            previous = current
            continue
        change = tuple(
            c - p if c is not None and p is not None else None for c, p in zip(current, previous)
        )
        previous = current
        if all(value in (0, None) for value in change):
            continue
        event = _base(options, session, f"{session}:token_count:{index}", time, "codex", None, None)
        event["payload"] = {
            "inputTokens": change[0],
            "outputTokens": change[1],
            "cacheReadTokens": change[2],
            "cacheWriteTokens": change[3],
            "complete": False,
            "category": "primary",
            "callId": None,
            "costUsd": None,
            "observationScope": "session_delta",
            "rawUsage": raw,
            "normalizerVersion": "codex-cumulative-1",
        }
        result.append(validate_event(event))
    return result
