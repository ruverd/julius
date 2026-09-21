"""Versioned local harness interface with no hidden model execution."""

from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from .artifacts import ArtifactStore
from .events import validate_event
from .ledger import Ledger
from .optimizer import optimize
from .query import query_window
from .reporting import report
from .xai import XAIAdapter, Transport
from .jev import Action, JevGateway, ShadowPolicy, shadow_decide
from dataclasses import asdict
from datetime import date


class Julius:
    def __init__(self, directory: str | Path):
        directory = Path(directory)
        self.artifacts = ArtifactStore(directory / "artifacts")
        self.ledger = Ledger(directory / "ledger.sqlite")

    def optimize(self, context: dict, policy: dict) -> dict:
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
                "category": "primary",
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
        receipt = self.record_usage(event)
        return {
            "requestedModel": result.requested_model,
            "actualModel": result.actual_model,
            "responseId": result.response_id,
            "complete": result.complete,
            "error": result.error,
            "usageEvent": event,
            "usageReceipt": receipt,
            "response": result.raw_response,
        }

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
            "disabled", "gateway_unavailable", "budget_unavailable", "invalid_timeout",
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
        )

    def close(self) -> None:
        self.ledger.close()

    def __enter__(self) -> "Julius":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
