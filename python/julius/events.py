"""Versioned, strict event schema for the append-only economy ledger."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


def _nonempty(value: str) -> str:
    if not value.strip():
        raise ValueError("Identifier must be nonempty")
    return value


def normalize_utc(value: str) -> str:
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid UTC date") from exc
    if instant.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return (
        instant.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


class PriceProvenance(StrictModel):
    priceSource: str
    priceDate: str
    priceModelId: str

    @field_validator("priceSource", "priceModelId")
    @classmethod
    def names(cls, value: str) -> str:
        return _nonempty(value)

    @field_validator("priceDate")
    @classmethod
    def date(cls, value: str) -> str:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Invalid price date")
        datetime.fromisoformat(value)
        return value


TokenCount = Annotated[int, Field(ge=0, le=9007199254740991)]
Money = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class TransformPayload(StrictModel):
    scope: Literal["tool_output", "request", "attempt", "task", "experiment"]
    inputTokens: TokenCount | None
    outputTokens: TokenCount | None
    tokenizer: str | None
    transformId: str
    parentTransformId: str | None
    inputArtifactId: str | None
    outputArtifactId: str | None
    strategy: str
    sent: bool

    @field_validator("transformId", "strategy")
    @classmethod
    def names(cls, value: str) -> str:
        return _nonempty(value)


class UsagePayload(StrictModel):
    inputTokens: TokenCount | None
    outputTokens: TokenCount | None
    cacheReadTokens: TokenCount | None
    cacheWriteTokens: TokenCount | None
    complete: bool
    category: Literal["primary", "auxiliary", "restoration"]
    callId: str | None
    costUsd: Money | None
    observationScope: Literal["call", "session_delta"] | None = None
    rawUsage: dict[str, Any] | None = None
    normalizerVersion: str | None = None
    costProvenance: PriceProvenance | None = None

    @model_validator(mode="after")
    def valid_cost(self) -> UsagePayload:
        if self.costUsd is not None and self.costProvenance is None:
            raise ValueError("Known cost requires provenance")
        if (
            self.inputTokens is not None
            and self.cacheReadTokens is not None
            and self.cacheReadTokens > self.inputTokens
        ):
            raise ValueError("Cache reads exceed input")
        return self


class DecisionPayload(StrictModel):
    decision: str
    reason: str | None
    strategy: str | None


class OutcomePayload(StrictModel):
    outcome: str
    reason: str | None


class ReconciliationPayload(StrictModel):
    targetEventId: str
    effectiveInputTokens: TokenCount | None
    effectiveOutputTokens: TokenCount | None
    effectiveCacheReadTokens: TokenCount | None
    effectiveCacheWriteTokens: TokenCount | None
    effectiveCostUsd: Money | None
    effectiveCostProvenance: PriceProvenance | None = None
    effectiveComplete: bool | None = None
    reason: str

    @model_validator(mode="after")
    def valid_cost(self) -> ReconciliationPayload:
        if self.effectiveCostUsd is not None and self.effectiveCostProvenance is None:
            raise ValueError("Known corrected cost requires provenance")
        return self


class EventBase(StrictModel):
    schemaVersion: Literal[1]
    eventId: str
    occurredAt: str
    sourceId: str
    sourceEventId: str
    projectId: str
    taskId: str | None
    sessionId: str
    requestId: str | None
    attemptId: str | None
    clientId: str
    adapterVersion: str
    modelId: str | None
    providerId: str | None
    executionLocation: Literal["local", "remote", "unknown"]
    evidence: Literal[
        "provider_reported",
        "runtime_reported",
        "tokenizer_counted",
        "heuristic_estimate",
        "reconstructed_baseline",
        "controlled_experiment",
    ]

    @field_validator(
        "eventId",
        "sourceId",
        "sourceEventId",
        "projectId",
        "sessionId",
        "clientId",
        "adapterVersion",
    )
    @classmethod
    def identifiers(cls, value: str) -> str:
        return _nonempty(value)

    @field_validator("occurredAt")
    @classmethod
    def timestamp(cls, value: str) -> str:
        if (
            not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value)
            or normalize_utc(value) != value
        ):
            raise ValueError("Canonical UTC milliseconds required")
        return value

    @model_validator(mode="after")
    def model_cost(self) -> EventBase:
        payload = getattr(self, "payload", None)
        if payload is not None:
            known_cost = (
                getattr(payload, "costUsd", None) is not None
                or getattr(payload, "effectiveCostUsd", None) is not None
            )
            if known_cost and self.modelId is None:
                raise ValueError("Known cost requires known model")
            provenance = getattr(payload, "costProvenance", None) or getattr(
                payload, "effectiveCostProvenance", None
            )
            if provenance is not None and provenance.priceModelId != self.modelId:
                raise ValueError("Price model does not match event model")
        return self


class TransformEvent(EventBase):
    eventType: Literal["transform"]
    payload: TransformPayload


class UsageEvent(EventBase):
    eventType: Literal["usage"]
    payload: UsagePayload


class DecisionEvent(EventBase):
    eventType: Literal["decision"]
    payload: DecisionPayload


class OutcomeEvent(EventBase):
    eventType: Literal["outcome"]
    payload: OutcomePayload


class ReconciliationEvent(EventBase):
    eventType: Literal["reconciliation"]
    payload: ReconciliationPayload


EconomyEvent = Annotated[
    Union[TransformEvent, UsageEvent, DecisionEvent, OutcomeEvent, ReconciliationEvent],
    Field(discriminator="eventType"),
]
_event_adapter: TypeAdapter[EconomyEvent] = TypeAdapter(EconomyEvent)


def validate_event(value: Any) -> dict[str, Any]:
    if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 65536:
        raise ValueError("Event exceeds 64 KiB limit")
    event = _event_adapter.validate_python(value, strict=True)
    return event.model_dump(exclude_none=False)
