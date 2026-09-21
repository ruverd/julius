"""Offline, compression-first attribution for one uncached sent request."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MAX_TOKENS = 2**53 - 1
MILLION = Decimal(1_000_000)
SCOPE = "one_sent_request_modeled_uncached_input"


class _StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class PinnedCount(_StrictModel):
    """A count pinned to one text digest, model, and tokenizer."""

    text_sha256: str | None
    model_id: str | None
    tokenizer_id: str | None
    tokens: int | None = Field(ge=0, le=MAX_TOKENS)

    @field_validator("text_sha256")
    @classmethod
    def valid_digest(cls, value: str | None) -> str | None:
        if value is not None and (
            len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
        ):
            raise ValueError("Text digest must be lowercase SHA-256 hex")
        return value


class InputPriceEvidence(_StrictModel):
    """Explicit dated USD rate for uncached input at one model."""

    snapshot_id: str | None
    model_id: str | None
    source: str | None
    source_date: date | None
    effective_at: datetime | None
    expires_at: datetime | None = None
    currency: str | None
    cache_regime: str | None
    input_usd_per_million: Decimal | None

    @field_validator("input_usd_per_million")
    @classmethod
    def valid_rate(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (not value.is_finite() or value < 0):
            raise ValueError("Input rate must be finite and nonnegative")
        return value

    @field_validator("effective_at", "expires_at")
    @classmethod
    def aware_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Price time must include a timezone")
        return value

    @model_validator(mode="after")
    def valid_window(self) -> InputPriceEvidence:
        if self.effective_at is not None and self.expires_at is not None:
            if self.expires_at <= self.effective_at:
                raise ValueError("Price expiry must follow effective time")
        return self


class InputCostAttribution(_StrictModel):
    """All evidence for the ordered baseline -> compressed -> routed comparison."""

    occurred_at: datetime
    baseline_model_id: str | None
    actual_model_id: str | None
    before_baseline: PinnedCount
    after_baseline: PinnedCount
    after_actual: PinnedCount
    baseline_price: InputPriceEvidence | None
    actual_price: InputPriceEvidence | None
    cache_regime: Literal["uncached", "warm", "mixed"] | None
    sent_acknowledged: bool

    @field_validator("occurred_at")
    @classmethod
    def aware_occurrence(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Request time must include a timezone")
        return value


def _known(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _price_available(
    price: InputPriceEvidence | None, model_id: str, occurred_at: datetime,
) -> bool:
    return bool(
        price is not None
        and _known(price.snapshot_id)
        and price.model_id == model_id
        and _known(price.source)
        and price.source_date is not None
        and price.source_date <= occurred_at.date()
        and price.effective_at is not None
        and price.effective_at <= occurred_at
        and (price.expires_at is None or occurred_at < price.expires_at)
        and price.currency == "USD"
        and price.cache_regime == "uncached"
        and price.input_usd_per_million is not None
    )


def _unavailable(reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": reason,
        "scope": SCOPE,
        "decompositionOrder": "compression_first",
        "baselineInputCostUsd": None,
        "compressedInputCostUsd": None,
        "actualInputCostUsd": None,
        "compressionSavingsUsd": None,
        "routingSavingsUsd": None,
        "totalSavingsUsd": None,
        "stages": None,
        "evidence": None,
    }


def attribute_input_cost(value: InputCostAttribution | dict[str, Any]) -> dict[str, Any]:
    """Attribute signed modeled input cost without subtracting cross-tokenizer counts.

    Unknown evidence returns no monetary result. Contradictory pinned identities
    raise ValueError, because they are invalid comparisons rather than unknowns.
    """
    data = InputCostAttribution.model_validate(value)
    before, compressed, actual = (
        data.before_baseline, data.after_baseline, data.after_actual
    )
    if not data.sent_acknowledged:
        return _unavailable("sent_acknowledgement_missing")
    if not _known(data.baseline_model_id) or not _known(data.actual_model_id):
        return _unavailable("model_unknown")
    baseline_model = data.baseline_model_id
    actual_model = data.actual_model_id
    assert baseline_model is not None and actual_model is not None
    for count, model in ((before, baseline_model), (compressed, baseline_model),
                         (actual, actual_model)):
        if count.model_id is not None and count.model_id != model:
            raise ValueError("Count model does not match comparison model")
    if (
        before.tokenizer_id is not None and compressed.tokenizer_id is not None
        and before.tokenizer_id != compressed.tokenizer_id
    ):
        raise ValueError("Baseline before/after counts use different tokenizers")
    if (
        baseline_model == actual_model
        and compressed.tokenizer_id is not None and actual.tokenizer_id is not None
        and compressed.tokenizer_id != actual.tokenizer_id
    ):
        raise ValueError("Same-model after counts use different tokenizers")
    if compressed.text_sha256 is not None and actual.text_sha256 is not None:
        if compressed.text_sha256 != actual.text_sha256:
            return _unavailable("after_text_differs")
        if compressed.tokenizer_id == actual.tokenizer_id and (
            compressed.tokens is not None and actual.tokens is not None
            and compressed.tokens != actual.tokens
        ):
            raise ValueError("Same text and tokenizer have incompatible counts")
    if data.cache_regime != "uncached":
        return _unavailable("cache_regime_unsupported")
    if any(
        count.tokens is None or not _known(count.model_id)
        or not _known(count.tokenizer_id) or count.text_sha256 is None
        for count in (before, compressed, actual)
    ):
        return _unavailable("count_evidence_unknown")
    if not _price_available(data.baseline_price, baseline_model, data.occurred_at):
        return _unavailable("baseline_price_unavailable")
    if not _price_available(data.actual_price, actual_model, data.occurred_at):
        return _unavailable("actual_price_unavailable")
    baseline_price, actual_price = data.baseline_price, data.actual_price
    assert baseline_price is not None and actual_price is not None
    if baseline_model == actual_model and baseline_price != actual_price:
        return _unavailable("same_model_price_mismatch")
    assert baseline_price.input_usd_per_million is not None
    assert actual_price.input_usd_per_million is not None
    assert baseline_price.source_date is not None
    assert actual_price.source_date is not None
    assert before.tokens is not None and compressed.tokens is not None
    assert actual.tokens is not None
    baseline_cost = Decimal(before.tokens) * baseline_price.input_usd_per_million / MILLION
    compressed_cost = Decimal(compressed.tokens) * baseline_price.input_usd_per_million / MILLION
    actual_cost = Decimal(actual.tokens) * actual_price.input_usd_per_million / MILLION
    compression = baseline_cost - compressed_cost
    routing = compressed_cost - actual_cost
    return {
        "status": "available",
        "reason": None,
        "scope": SCOPE,
        "decompositionOrder": "compression_first",
        "baselineInputCostUsd": baseline_cost,
        "compressedInputCostUsd": compressed_cost,
        "actualInputCostUsd": actual_cost,
        "compressionSavingsUsd": compression,
        "routingSavingsUsd": routing,
        "totalSavingsUsd": compression + routing,
        "stages": {
            "baseline": {
                "costUsd": baseline_cost, "tokens": before.tokens,
                "modelId": baseline_model, "tokenizerId": before.tokenizer_id,
                "textSha256": before.text_sha256,
                "priceSnapshotId": baseline_price.snapshot_id,
                "evidence": "pinned_count_and_dated_price",
            },
            "afterCompression": {
                "costUsd": compressed_cost, "tokens": compressed.tokens,
                "modelId": baseline_model, "tokenizerId": compressed.tokenizer_id,
                "textSha256": compressed.text_sha256,
                "priceSnapshotId": baseline_price.snapshot_id,
                "evidence": "pinned_count_and_dated_price",
            },
            "afterRouting": {
                "costUsd": actual_cost, "tokens": actual.tokens,
                "modelId": actual_model, "tokenizerId": actual.tokenizer_id,
                "textSha256": actual.text_sha256,
                "priceSnapshotId": actual_price.snapshot_id,
                "evidence": "pinned_count_dated_price_and_sent_acknowledgement",
            },
        },
        "evidence": {
            "counts": "pinned_tokenizer_counts",
            "sent": "caller_acknowledged",
            "baselinePriceSnapshotId": baseline_price.snapshot_id,
            "actualPriceSnapshotId": actual_price.snapshot_id,
            "baselinePriceSource": baseline_price.source,
            "actualPriceSource": actual_price.source,
            "baselinePriceSourceDate": baseline_price.source_date.isoformat(),
            "actualPriceSourceDate": actual_price.source_date.isoformat(),
            "baselineTokenizerId": before.tokenizer_id,
            "actualTokenizerId": actual.tokenizer_id,
            "afterTextSha256": compressed.text_sha256,
            "costBasis": "modeled_uncached_input_only",
        },
    }
