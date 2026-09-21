"""Caller-attested whole model-input measurement for embedded harnesses."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .ledger import Ledger
from .events import validate_event

TokenCounter = Callable[[str], int]


def record_embedded_request(
    ledger: Ledger, *, project_id: str, session_id: str, request_id: str,
    attempt_id: str, client_id: str, model_id: str, actual_model_id: str,
    response_id: str, before_input: str, after_input: str, sent_input: str,
    token_counter: TokenCounter, tokenizer_id: str, complete_model_input: bool,
    task_id: str | None = None, input_artifact_id: str | None = None,
    output_artifact_id: str | None = None,
    usage_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record one attested sent attempt; inputs are used in memory only.

    The caller supplies the entire model-visible input, including instructions and
    tool definitions. It also attests that the response belongs to the sent input.
    This does not establish provider token usage or causal savings.
    """
    identities = (project_id, session_id, request_id, attempt_id, client_id,
                  model_id, actual_model_id, response_id, tokenizer_id)
    if any(not isinstance(item, str) or not item.strip() for item in identities):
        raise ValueError("All request, response, model, and tokenizer IDs are required")
    if model_id != actual_model_id:
        raise ValueError("Responding model does not match tokenizer model")
    if complete_model_input is not True:
        raise ValueError("Complete model-visible input must be attested")
    if any(not isinstance(item, str) for item in (before_input, after_input, sent_input)):
        raise ValueError("Model-visible inputs must be strings")
    if sent_input != after_input:
        raise ValueError("Sent input differs from counted after-input")
    if not callable(token_counter):
        raise ValueError("A pinned token counter is required")
    counts = (token_counter(before_input), token_counter(after_input))
    if any(type(count) is not int or not 0 <= count <= 2**53 - 1 for count in counts):
        raise ValueError("Token counter returned an invalid count")
    before_bytes = before_input.encode("utf-8")
    after_bytes = after_input.encode("utf-8")
    before_hash = sha256(before_bytes).hexdigest()
    after_hash = sha256(after_bytes).hexdigest()

    key = json.dumps((project_id, session_id, request_id, attempt_id, client_id),
                     separators=(",", ":"), ensure_ascii=False)
    event_id = str(uuid5(NAMESPACE_URL, "julius-embedded-request:" + key))
    occurred_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    event = {
        "schemaVersion": 1, "eventId": event_id, "occurredAt": occurred_at,
        "sourceId": "julius-embedded-request", "sourceEventId": event_id,
        "projectId": project_id, "taskId": task_id, "sessionId": session_id,
        "requestId": request_id, "attemptId": attempt_id, "clientId": client_id,
        "adapterVersion": "0.1.0-experimental", "modelId": actual_model_id,
        "providerId": None, "executionLocation": "unknown",
        "eventType": "transform", "evidence": "tokenizer_counted",
        "payload": {
            "scope": "request", "inputTokens": counts[0], "outputTokens": counts[1],
            "tokenizer": tokenizer_id, "transformId": event_id,
            "parentTransformId": None, "inputArtifactId": input_artifact_id,
            "outputArtifactId": output_artifact_id,
            "strategy": "embedded_caller_attested_model_input", "sent": True,
            "responseId": response_id, "beforeSha256": before_hash,
            "afterSha256": after_hash, "beforeBytes": len(before_bytes),
            "afterBytes": len(after_bytes),
        },
    }
    if usage_event is None:
        event, receipt = ledger.record_generated_event(event)
    else:
        usage = validate_event(usage_event)
        if usage["eventType"] != "usage":
            raise ValueError("Companion must be a usage event")
        if usage["eventId"] == event_id:
            raise ValueError("Usage and transform IDs must differ")
        for field in ("projectId", "taskId", "sessionId", "requestId", "attemptId", "clientId", "modelId"):
            if usage[field] != event[field]:
                raise ValueError(f"Usage {field} does not match embedded attempt")
        if usage["payload"]["observationScope"] != "call":
            raise ValueError("Usage observationScope must be call")
        if not isinstance(usage["payload"]["callId"], str) or not usage["payload"]["callId"].strip():
            raise ValueError("Usage callId is required")
        event, receipts = ledger.record_generated_pair(event, usage)
        receipt = receipts[0]
    result = {
        "event": event, "ledgerReceipt": receipt,
        "attestation": "caller_attested_model_input", "responseId": response_id,
        "providerMeasured": False, "causalSavingsEstablished": False,
        "beforeSha256": before_hash,
        "afterSha256": after_hash,
        "beforeBytes": len(before_bytes), "afterBytes": len(after_bytes),
        "deltaTokens": counts[0] - counts[1],
    }
    if usage_event is not None:
        result["usageEvent"] = usage
        result["usageReceipt"] = receipts[1]
    return result
