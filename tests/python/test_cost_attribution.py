"""Offline, exact modeled input-cost attribution."""

from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from julius.cost_attribution import attribute_input_cost


BEFORE_HASH = "a" * 64
AFTER_HASH = "b" * 64
WHEN = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)


def case() -> dict:
    return {
        "occurred_at": WHEN,
        "baseline_model_id": "baseline-model",
        "actual_model_id": "actual-model",
        "before_baseline": {
            "text_sha256": BEFORE_HASH, "model_id": "baseline-model",
            "tokenizer_id": "baseline-tokenizer-v1", "tokens": 10_000,
        },
        "after_baseline": {
            "text_sha256": AFTER_HASH, "model_id": "baseline-model",
            "tokenizer_id": "baseline-tokenizer-v1", "tokens": 4_000,
        },
        "after_actual": {
            "text_sha256": AFTER_HASH, "model_id": "actual-model",
            "tokenizer_id": "actual-tokenizer-v1", "tokens": 4_500,
        },
        "baseline_price": {
            "snapshot_id": "baseline-price", "model_id": "baseline-model",
            "source": "explicit-contract", "source_date": date(2026, 9, 20),
            "effective_at": datetime(2026, 9, 20, tzinfo=timezone.utc),
            "currency": "USD", "cache_regime": "uncached",
            "input_usd_per_million": Decimal("10"),
        },
        "actual_price": {
            "snapshot_id": "actual-price", "model_id": "actual-model",
            "source": "explicit-contract", "source_date": date(2026, 9, 20),
            "effective_at": datetime(2026, 9, 20, tzinfo=timezone.utc),
            "currency": "USD", "cache_regime": "uncached",
            "input_usd_per_million": Decimal("5"),
        },
        "cache_regime": "uncached",
        "sent_acknowledged": True,
    }


def test_compression_first_decomposes_10000_to_4000_and_cheaper_route():
    result = attribute_input_cost(case())
    assert result["status"] == "available"
    assert result["decompositionOrder"] == "compression_first"
    assert result["baselineInputCostUsd"] == Decimal("0.1")
    assert result["compressedInputCostUsd"] == Decimal("0.04")
    assert result["actualInputCostUsd"] == Decimal("0.0225")
    assert result["compressionSavingsUsd"] == Decimal("0.06")
    assert result["routingSavingsUsd"] == Decimal("0.0175")
    assert result["totalSavingsUsd"] == Decimal("0.0775")
    assert result["totalSavingsUsd"] == (
        result["compressionSavingsUsd"] + result["routingSavingsUsd"]
    )
    assert result["stages"]["afterRouting"]["evidence"].endswith("sent_acknowledgement")
    assert result["evidence"]["costBasis"] == "modeled_uncached_input_only"


def test_negative_compression_and_routing_effects_remain_negative():
    data = case()
    data["after_baseline"]["tokens"] = 12_000
    data["after_actual"]["tokens"] = 13_000
    data["actual_price"]["input_usd_per_million"] = Decimal("20")
    result = attribute_input_cost(data)
    assert result["compressionSavingsUsd"] == Decimal("-0.02")
    assert result["routingSavingsUsd"] == Decimal("-0.14")
    assert result["totalSavingsUsd"] == Decimal("-0.16")


def test_cross_model_token_counts_are_not_subtracted_as_savings():
    data = case()
    data["actual_price"]["input_usd_per_million"] = Decimal("10")
    result = attribute_input_cost(data)
    assert result["routingSavingsUsd"] == Decimal("-0.005")
    assert "routingSavingsTokens" not in result


def test_same_model_requires_one_price_basis_and_has_zero_routing_effect():
    data = case()
    data["actual_model_id"] = "baseline-model"
    data["after_actual"]["model_id"] = "baseline-model"
    data["after_actual"]["tokenizer_id"] = "baseline-tokenizer-v1"
    data["after_actual"]["tokens"] = 4_000
    data["actual_price"] = deepcopy(data["baseline_price"])
    assert attribute_input_cost(data)["routingSavingsUsd"] == Decimal(0)
    data["actual_price"]["snapshot_id"] = "different-price"
    assert attribute_input_cost(data)["reason"] == "same_model_price_mismatch"


@pytest.mark.parametrize("field,value,reason", [
    ("cache_regime", "warm", "cache_regime_unsupported"),
    ("cache_regime", None, "cache_regime_unsupported"),
    ("sent_acknowledged", False, "sent_acknowledgement_missing"),
    ("actual_model_id", None, "model_unknown"),
])
def test_unknown_or_unsupported_inputs_leave_all_money_unavailable(field, value, reason):
    data = case()
    data[field] = value
    result = attribute_input_cost(data)
    assert result["status"] == "unavailable"
    assert result["reason"] == reason
    assert result["baselineInputCostUsd"] is None
    assert result["totalSavingsUsd"] is None


def test_missing_count_or_dated_price_is_unavailable():
    data = case()
    data["after_actual"]["tokens"] = None
    assert attribute_input_cost(data)["reason"] == "count_evidence_unknown"
    data = case()
    data["baseline_price"]["input_usd_per_million"] = None
    assert attribute_input_cost(data)["reason"] == "baseline_price_unavailable"
    data = case()
    data["actual_price"]["effective_at"] = datetime(2026, 9, 22, tzinfo=timezone.utc)
    assert attribute_input_cost(data)["reason"] == "actual_price_unavailable"


def test_different_after_text_cannot_be_attributed():
    data = case()
    data["after_actual"]["text_sha256"] = "c" * 64
    assert attribute_input_cost(data)["reason"] == "after_text_differs"


def test_incompatible_count_identities_are_rejected():
    data = case()
    data["after_baseline"]["tokenizer_id"] = "different-tokenizer"
    with pytest.raises(ValueError, match="different tokenizers"):
        attribute_input_cost(data)
    data = case()
    data["after_actual"]["model_id"] = "unrelated-model"
    with pytest.raises(ValueError, match="Count model"):
        attribute_input_cost(data)
    data = case()
    data["after_actual"]["tokenizer_id"] = data["after_baseline"]["tokenizer_id"]
    with pytest.raises(ValueError, match="incompatible counts"):
        attribute_input_cost(data)


def test_boolean_or_negative_counts_are_rejected():
    data = case()
    data["before_baseline"]["tokens"] = True
    with pytest.raises(ValidationError):
        attribute_input_cost(data)
    data = case()
    data["before_baseline"]["tokens"] = -1
    with pytest.raises(ValidationError):
        attribute_input_cost(data)


def test_input_is_not_mutated():
    data = case()
    original = deepcopy(data)
    attribute_input_cost(data)
    assert data == original
