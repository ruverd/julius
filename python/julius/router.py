"""Pure, fail-closed model routing at an explicitly supplied task boundary."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class ModelChoice(StrictModel):
    endpoint: str
    provider: str
    requested_model: str
    actual_model: str | None = None
    digest: str | None = None
    quantization: str | None = None
    tokenizer_id: str | None = None
    state: Literal["installed", "loaded", "available_remote", "unavailable", "unknown"]
    location: Literal["local", "remote"]
    context_window: int | None = Field(default=None, gt=0)
    supports_tools: bool | None = None
    supports_structured_output: bool | None = None
    observed_latency_ms: int | None = Field(default=None, ge=0)
    observed_concurrency_capacity: int | None = Field(default=None, ge=0)
    observed_concurrency_used: int | None = Field(default=None, ge=0)
    hardware_admitted: bool | None = None
    authorization_granted: bool | None = None
    evidence_id: str

    @model_validator(mode="after")
    def valid_identity(self) -> ModelChoice:
        if not all((self.endpoint.strip(), self.provider.strip(),
                    self.requested_model.strip(), self.evidence_id.strip())):
            raise ValueError("Model identity and evidence ID must be nonempty")
        return self

    @property
    def identity(self) -> tuple[str, str, str, str | None, str | None, str | None]:
        return (self.endpoint, self.provider, self.requested_model,
                self.actual_model, self.digest, self.quantization)


class PriceEvidence(StrictModel):
    model_identity: tuple[str, str, str, str | None, str | None, str | None]
    input_per_million: Decimal = Field(ge=0)
    output_per_million: Decimal = Field(ge=0)
    effective_at: datetime
    source: str

    @model_validator(mode="after")
    def valid_source(self) -> PriceEvidence:
        if self.effective_at.tzinfo is None or not self.source.strip():
            raise ValueError("Price evidence needs an aware date and source")
        return self


class TaskBoundary(StrictModel):
    boundary_id: str
    safe_to_switch: bool
    requires_tools: bool
    requires_structured_output: bool
    input_tokens: int = Field(ge=0)
    expected_output_tokens: int = Field(ge=0)
    forecast_tokenizer_id: str
    forecast_evidence_id: str
    minimum_context_tokens: int = Field(ge=0)
    allowed_locations: frozenset[Literal["local", "remote"]]
    allowed_endpoints: frozenset[str]
    maximum_latency_ms: int | None = Field(default=None, ge=0)
    maximum_spend: Decimal | None = Field(default=None, ge=0)
    minimum_savings_fraction: Decimal = Field(default=Decimal("0.1"), ge=0, lt=1)

    @model_validator(mode="after")
    def valid_boundary(self) -> TaskBoundary:
        if not all((self.boundary_id.strip(), self.forecast_tokenizer_id.strip(),
                    self.forecast_evidence_id.strip())):
            raise ValueError("Boundary and token forecast evidence must be nonempty")
        return self


class RouteDecision(StrictModel):
    boundary_id: str
    selected: ModelChoice
    switched: bool
    dispatch_allowed: bool
    reason: str
    current_evidence_id: str
    selected_evidence_id: str
    forecast_evidence_id: str
    current_predicted_cost: Decimal | None
    selected_predicted_cost: Decimal | None
    predicted_savings: Decimal | None
    price_sources: tuple[str, ...]
    decided_at: datetime


def _cost(model: ModelChoice, prices: tuple[PriceEvidence, ...], boundary: TaskBoundary,
          now: datetime, max_price_age: timedelta) -> tuple[Decimal, str] | None:
    if model.tokenizer_id is None or model.tokenizer_id != boundary.forecast_tokenizer_id:
        return None
    matching = [p for p in prices if p.model_identity == model.identity
                and p.effective_at <= now and now - p.effective_at <= max_price_age]
    if not matching:
        return None
    price = max(matching, key=lambda p: (p.effective_at, p.source))
    amount = ((price.input_per_million * boundary.input_tokens
               + price.output_per_million * boundary.expected_output_tokens)
              / Decimal(1_000_000))
    return amount, price.source


def _eligible(model: ModelChoice, boundary: TaskBoundary) -> bool:
    if model.tokenizer_id is None or model.tokenizer_id != boundary.forecast_tokenizer_id:
        return False
    if model.authorization_granted is not True:
        return False
    if model.endpoint not in boundary.allowed_endpoints or model.location not in boundary.allowed_locations:
        return False
    if model.location == "local":
        if model.state != "loaded" or model.hardware_admitted is not True:
            return False
    elif model.state != "available_remote":
        return False
    if model.context_window is None or model.context_window < max(
        boundary.minimum_context_tokens, boundary.input_tokens + boundary.expected_output_tokens
    ):
        return False
    if boundary.requires_tools and model.supports_tools is not True:
        return False
    if boundary.requires_structured_output and model.supports_structured_output is not True:
        return False
    if boundary.maximum_latency_ms is not None and (
        model.observed_latency_ms is None or model.observed_latency_ms > boundary.maximum_latency_ms
    ):
        return False
    if (model.observed_concurrency_capacity is None
            or model.observed_concurrency_used is None
            or model.observed_concurrency_used >= model.observed_concurrency_capacity):
        return False
    return True


def decide_route(*, boundary: TaskBoundary, current: ModelChoice,
                 candidates: tuple[ModelChoice, ...], prices: tuple[PriceEvidence, ...],
                 now: datetime, max_price_age: timedelta = timedelta(days=30)) -> RouteDecision:
    """Return a recommendation only; this function never calls a model or changes a client."""
    if now.tzinfo is None or max_price_age < timedelta(0):
        raise ValueError("Decision time must be aware and price age nonnegative")
    current_price = _cost(current, prices, boundary, now, max_price_age)
    selected = current
    selected_price = current_price
    reason = "no_eligible_cheaper_candidate"
    if not boundary.safe_to_switch:
        reason = "unsafe_boundary"
    elif not _eligible(current, boundary):
        reason = "current_eligibility_unverified"
    elif current_price is None:
        reason = "current_price_unknown"
    else:
        affordable: list[tuple[Decimal, ModelChoice, str]] = []
        for candidate in candidates:
            if candidate.identity == current.identity or not _eligible(candidate, boundary):
                continue
            candidate_price = _cost(candidate, prices, boundary, now, max_price_age)
            if candidate_price is None:
                continue
            cost, source = candidate_price
            if boundary.maximum_spend is not None and cost > boundary.maximum_spend:
                continue
            if cost >= current_price[0] * (1 - boundary.minimum_savings_fraction):
                continue
            affordable.append((cost, candidate, source))
        if affordable:
            cost, selected, source = min(affordable, key=lambda item: (item[0], repr(item[1].identity)))
            selected_price = (cost, source)
            reason = "cheaper_eligible_candidate"
        elif boundary.maximum_spend is not None and current_price[0] > boundary.maximum_spend:
            reason = "budget_exceeded_no_eligible_alternative"
    return RouteDecision(
        boundary_id=boundary.boundary_id, selected=selected,
        switched=selected.identity != current.identity, reason=reason,
        dispatch_allowed=(_eligible(selected, boundary)
                          and (boundary.maximum_spend is None
                               or (selected_price is not None
                                   and selected_price[0] <= boundary.maximum_spend))),
        current_evidence_id=current.evidence_id, selected_evidence_id=selected.evidence_id,
        forecast_evidence_id=boundary.forecast_evidence_id,
        current_predicted_cost=current_price[0] if current_price else None,
        selected_predicted_cost=selected_price[0] if selected_price else None,
        predicted_savings=(current_price[0] - selected_price[0]
                           if current_price and selected_price else None),
        price_sources=tuple(p[1] for p in (current_price, selected_price) if p is not None),
        decided_at=now,
    )
