"""Versioned local harness interface with no hidden model execution."""

from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from .artifacts import ArtifactStore
from .events import validate_event
from .ledger import Ledger
from .optimizer import STRATEGY_ID, STRATEGY_VERSION, optimize
from .quality_guard import GuardPolicy, Scope
from .quality_store import QualityStore
from .query import query_window
from .reporting import report
from .xai import XAIAdapter, XAIResult, Transport
from .xai_tool_loop import run_restore_loop
from .xai_optimization import prepare_optimized_request
from .request_measurement import TokenCounter, TokenCountingBasis
from .embedded_request import record_embedded_request
from .jev import Action, JevGateway, ShadowPolicy, shadow_decide
from dataclasses import asdict
from datetime import date


def _request_token_comparison(
    measurement: Mapping[str, Any], actual_model: str | None,
) -> tuple[bool, str | None]:
    if measurement.get("beforeTokens") is None or measurement.get("afterTokens") is None:
        return False, "counter_unavailable"
    if measurement.get("tokenCountingBasis") != "model_input":
        return False, "serialized_request_only"
    if actual_model is None:
        return False, "actual_model_unavailable"
    if measurement.get("modelId") != actual_model:
        return False, "actual_model_mismatch"
    return False, "caller_counter_cannot_verify_model_input"


class Julius:
    def __init__(self, directory: str | Path):
        directory = Path(directory)
        self.directory = directory
        self.artifacts = ArtifactStore(directory / "artifacts")
        self.ledger = Ledger(directory / "ledger.sqlite")

    def optimize(
        self, context: dict, policy: dict, *,
        quality_scope: Scope | None = None,
        quality_policy: GuardPolicy | None = None,
    ) -> dict:
        if (quality_scope is None) != (quality_policy is None):
            raise ValueError("Quality scope and policy must be supplied together")
        if quality_scope is not None and quality_policy is not None:
            if context.get("projectId") != quality_scope.project_id:
                raise ValueError("Quality scope does not match optimization project")
            if context.get("modelId") != quality_scope.model_id:
                raise ValueError("Quality scope requires the matching model ID")
            if (quality_scope.strategy_id, quality_scope.strategy_version) != (
                STRATEGY_ID, STRATEGY_VERSION,
            ):
                raise ValueError("Quality scope does not match optimizer strategy")
            try:
                with QualityStore(self.directory / "quality.sqlite") as store:
                    decision = store.decision(quality_scope, quality_policy)
            except (OSError, sqlite3.Error, ValueError) as exc:
                raise RuntimeError("Quality guard unavailable; optimization blocked") from exc
            if decision["status"] != "enabled":
                raise RuntimeError(f"Quality guard blocked optimization: {decision['status']}")
        eligibility = optimize({**context, "recovery": None}, policy)
        if eligibility["receipt"]["reason"] != "recovery_required":
            return {**eligibility, "original": None}
        original = self.artifacts.put(context["projectId"], context["content"])
        try:
            result = optimize(
                {**context, "recovery": {"artifactId": original["id"], "available": True}}, policy
            )
        except Exception:
            self.artifacts.delete(context["projectId"], original["id"])
            raise
        if not result["receipt"]["applied"]:
            self.artifacts.delete(context["projectId"], original["id"])
            return {**result, "original": None}
        return {**result, "original": original}

    def record_usage(self, event: dict) -> dict:
        event = validate_event(event)
        if event["eventType"] != "usage":
            raise ValueError("record_usage requires a usage event")
        return self.ledger.record(event)

    def record_outcome(self, event: dict) -> dict:
        event = validate_event(event)
        if event["eventType"] != "outcome":
            raise ValueError("record_outcome requires an outcome event")
        return self.ledger.record(event)

    def record_embedded_request(
        self, *, project_id: str, session_id: str, request_id: str,
        attempt_id: str, client_id: str, model_id: str, actual_model_id: str,
        response_id: str, before_input: str, after_input: str, sent_input: str,
        token_counter: TokenCounter, tokenizer_id: str, complete_model_input: bool,
        task_id: str | None = None, input_artifact_id: str | None = None,
        output_artifact_id: str | None = None,
    ) -> dict[str, Any]:
        """Record a caller-attested complete model-input reduction."""
        return record_embedded_request(
            self.ledger, project_id=project_id, session_id=session_id,
            request_id=request_id, attempt_id=attempt_id, client_id=client_id,
            model_id=model_id, actual_model_id=actual_model_id,
            response_id=response_id, before_input=before_input,
            after_input=after_input, sent_input=sent_input,
            token_counter=token_counter, tokenizer_id=tokenizer_id,
            complete_model_input=complete_model_input, task_id=task_id,
            input_artifact_id=input_artifact_id,
            output_artifact_id=output_artifact_id,
        )

    def send_xai(
        self,
        request: Mapping[str, Any],
        *,
        api_key: str,
        project_id: str,
        session_id: str,
        task_id: str | None = None,
        transport: Transport | None = None,
    ) -> dict[str, Any]:
        """Execute one explicit xAI request; preserve provider usage even when incomplete."""
        if not project_id or not session_id:
            raise ValueError("Project and session identity are required")
        adapter = XAIAdapter()
        adapter.prepare(request)
        request_id = str(uuid4())
        attempt_id = str(uuid4())
        result = adapter.send_once(request, api_key, transport=transport)
        event = None
        receipt = None
        recording_error = None
        try:
            event, receipt = self._record_xai_attempt(
                result, project_id=project_id, session_id=session_id, task_id=task_id,
                request_id=request_id, attempt_id=attempt_id,
            )
        except Exception:
            # A provider call has already happened. Preserve its returned evidence
            # without retrying or implying that the ledger has no matching row.
            recording_error = "ledger_recording_status_unknown"
        return {
            "requestedModel": result.requested_model,
            "actualModel": result.actual_model,
            "responseId": result.response_id,
            "complete": result.complete,
            "error": result.error,
            "usageEvent": event,
            "usageReceipt": receipt,
            "recordingError": recording_error,
            "ledgerRecordingStatus": "unknown" if recording_error else "recorded",
            "attemptEvidence": self._xai_attempt_evidence(result),
            "response": result.raw_response,
        }

    @staticmethod
    def _xai_attempt_evidence(result: XAIResult) -> dict[str, Any]:
        """Expose provider observations when local recording has an unknown outcome."""
        return {
            "requestedModel": result.requested_model,
            "actualModel": result.actual_model,
            "responseId": result.response_id,
            "complete": result.complete,
            "inputTokens": result.input_tokens,
            "outputTokens": result.output_tokens,
            "cachedInputTokens": result.cached_input_tokens,
            "reasoningTokens": result.reasoning_tokens,
            "totalTokens": result.total_tokens,
            "costTicks": result.cost_ticks,
            "rawUsage": result.raw_usage,
            "error": result.error,
            "evidence": result.evidence,
            "transportBodySha256": result.transport_body_sha256,
            "transportBodyBytes": result.transport_body_bytes,
        }

    def _record_xai_attempt(
        self, result: XAIResult, *, project_id: str, session_id: str,
        task_id: str | None, request_id: str, attempt_id: str,
        category: str = "primary",
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Record one actual attempted Responses call, including incomplete calls."""
        provider_charge = (
            result.cost_ticks / 10_000_000_000
            if result.cost_ticks is not None and result.actual_model is not None
            else None
        )
        event_id = str(uuid4())
        event = {
            "schemaVersion": 1,
            "eventId": event_id,
            "occurredAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "sourceId": "julius-xai-responses",
            "sourceEventId": event_id,
            "projectId": project_id,
            "taskId": task_id,
            "sessionId": session_id,
            "requestId": request_id,
            "attemptId": attempt_id,
            "clientId": "julius-xai",
            "adapterVersion": "0.1.0-experimental",
            "modelId": result.actual_model,
            "providerId": "xai",
            "executionLocation": "remote",
            "eventType": "usage",
            "evidence": "provider_reported" if result.raw_usage is not None else "runtime_reported",
            "payload": {
                "inputTokens": result.input_tokens,
                "outputTokens": result.output_tokens,
                "cacheReadTokens": result.cached_input_tokens,
                "cacheWriteTokens": None,
                "complete": result.complete,
                "category": category,
                "callId": result.response_id,
                "costUsd": provider_charge,
                "costProvenance": {
                    "chargeSource": "provider_usage",
                    "chargeField": "usage.cost_in_usd_ticks",
                    "chargeUnit": "usd_ticks_1e10",
                    "chargeModelId": result.actual_model,
                } if provider_charge is not None else None,
                "observationScope": "call",
                "rawUsage": result.raw_usage,
                "normalizerVersion": "xai-responses-1",
            },
        }
        return event, self.record_usage(event)

    def send_xai_with_restores(
        self,
        request: Mapping[str, Any],
        *,
        api_key: str,
        project_id: str,
        session_id: str,
        task_id: str | None = None,
        transport: Transport | None = None,
        max_calls: int = 4,
    ) -> dict[str, Any]:
        """Explicitly send and serve Julius restores; record each provider attempt."""
        if not project_id or not session_id:
            raise ValueError("Project and session identity are required")
        records: list[dict[str, Any]] = []

        def record_attempt(result: XAIResult, index: int) -> None:
            event, receipt = self._record_xai_attempt(
                result, project_id=project_id, session_id=session_id, task_id=task_id,
                request_id=str(uuid4()), attempt_id=str(uuid4()),
                category="primary" if index == 0 else "restoration",
            )
            records.append({"usageEvent": event, "usageReceipt": receipt})

        outcome = run_restore_loop(
            request, api_key=api_key, project_id=project_id, artifacts=self.artifacts,
            transport=transport, max_calls=max_calls, on_attempt=record_attempt,
        )
        return {
            "complete": outcome.completed,
            "error": outcome.error,
            "attempts": records,
            "attemptEvidence": [self._xai_attempt_evidence(item) for item in outcome.attempts],
            "ledgerRecordingStatus": (
                "unknown" if len(records) != len(outcome.attempts) else "recorded"
            ),
            "responses": [attempt.raw_response for attempt in outcome.attempts],
            "restoredArtifactIds": list(outcome.restored_artifact_ids),
        }

    def send_xai_optimized(
        self,
        request: Mapping[str, Any],
        *,
        api_key: str,
        project_id: str,
        session_id: str,
        policy: dict[str, Any],
        task_id: str | None = None,
        transport: Transport | None = None,
        max_calls: int = 4,
        token_counter: TokenCounter | None = None,
        tokenizer_model_id: str | None = None,
        tokenizer_id: str | None = None,
        token_counting_basis: TokenCountingBasis = "serialized_request",
    ) -> dict[str, Any]:
        """Explicitly prepare, send, and account for a recoverable xAI candidate."""
        if not project_id or not session_id:
            raise ValueError("Project and session identity are required")
        if not api_key or any(character in api_key for character in "\r\n"):
            raise ValueError("A valid dedicated xAI API key is required")
        if type(max_calls) is not int or not 1 <= max_calls <= 32:
            raise ValueError("max_calls must be between 1 and 32")
        if not isinstance(request, Mapping):
            raise ValueError("Responses request must be an object")
        if request.get("store") is False:
            raise ValueError("Continuation with store=false is not verified")
        # Validate the complete request before creating recoverable artifacts.
        XAIAdapter().prepare(request)
        prepared = prepare_optimized_request(
            request, project_id=project_id, policy=policy, artifacts=self.artifacts,
            recovery_handler_available=True,
            token_counter=token_counter, tokenizer_model_id=tokenizer_model_id,
            tokenizer_id=tokenizer_id,
            token_counting_basis=token_counting_basis,
        )
        outcome = self.send_xai_with_restores(
            prepared.request, api_key=api_key, project_id=project_id,
            session_id=session_id, task_id=task_id, transport=transport,
            max_calls=max_calls,
        )
        if outcome["ledgerRecordingStatus"] != "recorded":
            # The candidate may have reached xAI, but no transform claim is
            # durable until the attempted call is reconciled in the ledger.
            measurement = dict(prepared.measurement or {})
            first_evidence = outcome["attemptEvidence"][0] if outcome["attemptEvidence"] else None
            actual_model = first_evidence["actualModel"] if first_evidence else None
            measurement["sent"] = None
            measurement["actualModelId"] = actual_model
            valid, reason = _request_token_comparison(measurement, actual_model)
            measurement["tokenComparisonValid"] = valid
            measurement["tokenComparisonReason"] = reason
            return {**outcome, "candidateReceipts": list(prepared.receipts),
                    "requestMeasurement": measurement,
                    "requestTransformEvent": None, "requestTransformReceipt": None,
                    "transformEvents": []}
        first = outcome["attempts"][0] if outcome["attempts"] else None
        first_event = first["usageEvent"] if first is not None else None
        first_response = outcome["responses"][0] if outcome["responses"] else None
        first_evidence = outcome["attemptEvidence"][0] if outcome["attemptEvidence"] else None
        measurement = dict(prepared.measurement or {})
        body_matches = bool(
            first_evidence is not None
            and first_evidence.get("transportBodySha256") == measurement.get("afterSha256")
            and first_evidence.get("transportBodyBytes") == measurement.get("afterBytes")
        )
        response_acknowledged = bool(
            first_event is not None and isinstance(first_response, dict)
            and first_response.get("status") == "completed"
            and isinstance(first_response.get("id"), str) and first_response["id"]
            and first_response["id"] == first_event["payload"]["callId"]
            and isinstance(first_response.get("model"), str) and first_response["model"]
            and first_response["model"] == first_event["modelId"]
            and body_matches
        )
        transformed = any(receipt["applied"] for receipt in prepared.receipts)
        measurement["bodyIdentityMatches"] = body_matches
        actual_model = first_event["modelId"] if first_event is not None else None
        valid_token_count, comparison_reason = _request_token_comparison(
            measurement, actual_model,
        )
        measurement["sent"] = bool(response_acknowledged and transformed)
        measurement["actualModelId"] = actual_model
        measurement["tokenComparisonValid"] = valid_token_count
        measurement["tokenComparisonReason"] = comparison_reason
        request_event_id = str(uuid4())
        request_event = {
            "schemaVersion": 1,
            "eventId": request_event_id,
            "occurredAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "sourceId": "julius-xai-request-measurement",
            "sourceEventId": request_event_id,
            "projectId": project_id,
            "taskId": task_id,
            "sessionId": session_id,
            "requestId": first_event["requestId"] if first_event is not None else str(uuid4()),
            "attemptId": first_event["attemptId"] if first_event is not None else str(uuid4()),
            "clientId": "julius-xai",
            "adapterVersion": "0.1.0-experimental",
            "modelId": actual_model,
            "providerId": "xai",
            "executionLocation": "remote" if response_acknowledged else "unknown",
            "eventType": "transform",
            "evidence": "tokenizer_counted" if valid_token_count else "heuristic_estimate",
            "payload": {
                "scope": "request",
                "inputTokens": measurement.get("beforeTokens") if valid_token_count else None,
                "outputTokens": measurement.get("afterTokens") if valid_token_count else None,
                "tokenizer": measurement.get("tokenizerId") if valid_token_count else None,
                "transformId": request_event_id,
                "parentTransformId": None,
                "inputArtifactId": None,
                "outputArtifactId": None,
                "strategy": "full_request_candidate",
                "sent": measurement["sent"],
            },
        }
        request_ledger_receipt = self.ledger.record(validate_event(request_event))
        transforms: list[dict[str, Any]] = []
        for receipt in prepared.receipts:
            event_id = str(uuid4())
            artifact_id = receipt["lineage"]["originalArtifactId"]
            event = {
                "schemaVersion": 1,
                "eventId": event_id,
                "occurredAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "sourceId": "julius-xai-optimization",
                "sourceEventId": event_id,
                "projectId": project_id,
                "taskId": task_id,
                "sessionId": session_id,
                "requestId": first_event["requestId"] if first_event is not None else str(uuid4()),
                "attemptId": first_event["attemptId"] if first_event is not None else str(uuid4()),
                "clientId": "julius-xai",
                "adapterVersion": "0.1.0-experimental",
                "modelId": first_event["modelId"] if first_event is not None else None,
                "providerId": "xai",
                "executionLocation": "remote" if response_acknowledged else "unknown",
                "eventType": "transform",
                "evidence": "heuristic_estimate",
                "payload": {
                    "scope": "tool_output",
                    "inputTokens": receipt["beforeTokens"],
                    "outputTokens": receipt["afterTokens"],
                    "tokenizer": None,
                    "transformId": event_id,
                    "parentTransformId": None,
                    "inputArtifactId": artifact_id,
                    "outputArtifactId": None,
                    "strategy": receipt["reason"],
                    "sent": bool(response_acknowledged and receipt["applied"]),
                },
            }
            transforms.append({"receipt": receipt, "event": event,
                               "ledgerReceipt": self.ledger.record(validate_event(event))})
        return {**outcome, "candidateReceipts": list(prepared.receipts),
                "requestMeasurement": measurement,
                "requestTransformEvent": request_event,
                "requestTransformReceipt": request_ledger_receipt,
                "transformEvents": transforms}

    def evaluate_jev_shadow(
        self,
        *,
        state: Mapping[str, int | float | bool | str],
        eligible_actions: tuple[Action, ...],
        policy: ShadowPolicy,
        project_id: str,
        session_id: str,
        task_id: str | None = None,
        gateway: JevGateway | None = None,
        price_source: str | None = None,
        price_date: str | None = None,
    ) -> dict[str, Any]:
        """Opt-in Jev shadow call; always keep deterministic production action."""
        if not project_id or not session_id:
            raise ValueError("Project and session identity are required")
        result = shadow_decide(
            state=state, eligible_actions=eligible_actions, policy=policy, gateway=gateway
        )
        no_call = {
            "disabled", "gateway_unavailable", "budget_unavailable", "precall_guard_rejected", "invalid_timeout",
            "invalid_eligible_action", "no_eligible_action", "invalid_confidence_threshold",
        }
        now = datetime.now(timezone.utc)
        common = {
            "schemaVersion": 1,
            "occurredAt": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "sourceId": "julius-jev-shadow",
            "projectId": project_id,
            "taskId": task_id,
            "sessionId": session_id,
            "requestId": str(uuid4()),
            "attemptId": str(uuid4()),
            "clientId": "julius-jev",
            "adapterVersion": "0.1.0-experimental",
            "modelId": result.actual_model,
            "providerId": "typesafe",
            "executionLocation": "remote" if result.reason not in no_call else "unknown",
        }
        decision_id = str(uuid4())
        decision = {
            **common,
            "eventId": decision_id,
            "sourceEventId": decision_id,
            "eventType": "decision",
            "evidence": "runtime_reported",
            "payload": {
                "decision": "keep",
                "reason": f"{result.reason}; proposed={result.proposed_action or 'unknown'}",
                "strategy": "jev_shadow",
            },
        }
        records = [decision]
        if result.reason not in no_call:
            usage_id = str(uuid4())
            price_valid = False
            if price_source and price_date:
                try:
                    price_valid = date.fromisoformat(price_date).isoformat() == price_date
                except ValueError:
                    price_valid = False
            cost_known = result.cost_usd is not None and result.actual_model is not None and price_valid
            records.append({
                **common,
                "eventId": usage_id,
                "sourceEventId": usage_id,
                "eventType": "usage",
                "evidence": "provider_reported" if result.input_tokens is not None and result.output_tokens is not None else "runtime_reported",
                "payload": {
                    "inputTokens": result.input_tokens,
                    "outputTokens": result.output_tokens,
                    "cacheReadTokens": None,
                    "cacheWriteTokens": None,
                    "complete": result.input_tokens is not None and result.output_tokens is not None,
                    "category": "auxiliary",
                    "callId": usage_id,
                    "costUsd": result.cost_usd if cost_known else None,
                    "costProvenance": {
                        "priceSource": price_source,
                        "priceDate": price_date,
                        "priceModelId": result.actual_model,
                    } if cost_known else None,
                    "observationScope": "call",
                    "normalizerVersion": "typesafe-systemone-1",
                },
            })
        receipts = self.ledger.record_many(records)
        return {"shadow": asdict(result), "events": records, "receipts": receipts}

    def report(self, query: dict | None = None) -> dict:
        query = query or {}
        window = query_window(query)
        return report(
            self.ledger.events({**query, "since": window["since"], "until": window["until"]}),
            window,
            by=query.get("by", "model"),
        )

    def close(self) -> None:
        self.ledger.close()

    def __enter__(self) -> "Julius":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
