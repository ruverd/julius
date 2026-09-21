"""Bounded xAI Responses continuation for project-scoped Julius restores."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, Mapping

from .artifacts import ArtifactStore
from .xai import Transport, XAIAdapter, XAIResult
from .xai_optimization import RECOVERY_TOOL, _has_recovery_tool


@dataclass(frozen=True)
class XAIToolLoopResult:
    attempts: tuple[XAIResult, ...]
    completed: bool
    error: str | None
    restored_artifact_ids: tuple[str, ...]


def run_restore_loop(
    request: Mapping[str, Any],
    *,
    api_key: str,
    project_id: str,
    artifacts: ArtifactStore,
    transport: Transport | None = None,
    max_calls: int = 4,
    on_attempt: Callable[[XAIResult, int], None] | None = None,
) -> XAIToolLoopResult:
    """Send each Responses request once, serving only verified Julius restores.

    Every attempted provider call is returned for later ledger recording. An
    ambiguous transport failure is terminal; this function never retries.
    """
    if type(max_calls) is not int or not 1 <= max_calls <= 32:
        raise ValueError("max_calls must be between 1 and 32")
    if not isinstance(request, Mapping):
        raise ValueError("Responses request must be an object")
    if not _has_recovery_tool(request):
        raise ValueError("A declared Julius restore function is required")
    if request.get("store") is False:
        raise ValueError("Continuation with store=false is not verified")
    current = copy.deepcopy(dict(request))
    adapter = XAIAdapter()
    attempts: list[XAIResult] = []
    restored: list[str] = []
    seen_calls: set[str] = set()
    while True:
        result = adapter.send_once(current, api_key, transport)
        attempts.append(result)
        if on_attempt is not None:
            # Persist this call before any continuation can be sent.
            on_attempt(result, len(attempts) - 1)
        if not result.complete or result.raw_response is None:
            return XAIToolLoopResult(tuple(attempts), False,
                                     result.error or "Provider response incomplete", tuple(restored))
        output = result.raw_response.get("output")
        if not isinstance(output, list):
            return XAIToolLoopResult(tuple(attempts), False, "Missing response output", tuple(restored))
        calls = [item for item in output if isinstance(item, dict) and item.get("type") == "function_call"]
        if any(not isinstance(item, dict) for item in output):
            return XAIToolLoopResult(tuple(attempts), False, "Malformed response output", tuple(restored))
        if not calls:
            return XAIToolLoopResult(tuple(attempts), True, None, tuple(restored))
        if not result.response_id:
            return XAIToolLoopResult(tuple(attempts), False, "Missing response ID", tuple(restored))
        if len(seen_calls) + len(calls) > max_calls:
            return XAIToolLoopResult(tuple(attempts), False, "Restore call limit exceeded", tuple(restored))
        parsed: list[tuple[str, str]] = []
        for call in calls:
            call_id = call.get("call_id")
            if call.get("name") != RECOVERY_TOOL:
                return XAIToolLoopResult(tuple(attempts), False,
                                         "Non-Julius function call", tuple(restored))
            if not isinstance(call_id, str) or not call_id or call_id in seen_calls:
                return XAIToolLoopResult(tuple(attempts), False,
                                         "Invalid or repeated call ID", tuple(restored))
            if any(existing == call_id for existing, _ in parsed):
                return XAIToolLoopResult(tuple(attempts), False,
                                         "Repeated call ID", tuple(restored))
            try:
                args = json.loads(call["arguments"])
            except (KeyError, TypeError, ValueError):
                return XAIToolLoopResult(tuple(attempts), False,
                                         "Malformed restore arguments", tuple(restored))
            if (not isinstance(args, dict) or set(args) != {"artifact_id"}
                    or not isinstance(args["artifact_id"], str)):
                return XAIToolLoopResult(tuple(attempts), False,
                                         "Malformed restore arguments", tuple(restored))
            parsed.append((call_id, args["artifact_id"]))
        replies: list[dict[str, str]] = []
        for call_id, artifact_id in parsed:
            try:
                original = artifacts.get(project_id, artifact_id)
            except (OSError, ValueError, KeyError, FileNotFoundError):
                return XAIToolLoopResult(tuple(attempts), False,
                                         "Original unavailable", tuple(restored))
            replies.append({"type": "function_call_output", "call_id": call_id,
                            "output": original})
        seen_calls.update(call_id for call_id, _ in parsed)
        restored.extend(artifact_id for _, artifact_id in parsed)
        current = copy.deepcopy(dict(request))
        current["input"] = replies
        current["previous_response_id"] = result.response_id
