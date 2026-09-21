"""The local price store supplies selected evidence to offline task economics."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from julius.economics import analyze_task
from julius.price_store import PriceSnapshot, PriceStore
from julius.pricing import price_usage


WHEN = datetime(2026, 9, 21, tzinfo=timezone.utc)


def snapshot(**changes: object) -> PriceSnapshot:
    values = {
        "endpoint": "https://api.example.test/v1",
        "provider": "vendor",
        "model": "m",
        "currency": "USD",
        "tier": "standard",
        "cache_regime": "default",
        "source": "dated-provider-price-page",
        "source_date": date(2026, 9, 1),
        "effective_at": datetime(2026, 9, 10, tzinfo=timezone.utc),
        "expires_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
        "rates_per_million": {
            "inputUncached": Decimal("10"),
            "cacheRead": Decimal("1"),
            "cacheWrite": Decimal("20"),
            "output": Decimal("30"),
        },
        "contracted_rate_per_million": Decimal("8"),
    }
    values.update(changes)
    return PriceSnapshot(**values)


def usage(snapshot_id: str, *, cache_read_tokens: int = 500) -> dict:
    return {
        "callId": "call", "modelId": "m", "providerId": "vendor",
        "inputTokens": 1000, "cacheReadTokens": cache_read_tokens,
        "cacheWriteTokens": 100, "outputTokens": 200,
        "priceSnapshotId": snapshot_id, "occurredAt": WHEN.isoformat(),
    }


def event(snapshot_id: str) -> dict:
    return {
        "eventId": "event", "eventType": "usage", "taskId": "task",
        "occurredAt": WHEN.isoformat(), "modelId": "m", "providerId": "vendor",
        "executionLocation": "remote", "evidence": "provider_reported",
        "payload": {
            "callId": "call", "inputTokens": 1000, "cacheReadTokens": 500,
            "cacheWriteTokens": 100, "outputTokens": 200,
            "priceSnapshotId": snapshot_id, "category": "primary", "complete": True,
            "costUsd": None, "costProvenance": None,
        },
    }


def test_selected_snapshot_prices_cached_usage_and_task(tmp_path):
    with PriceStore(tmp_path / "prices.sqlite") as store:
        recorded = store.record(snapshot())
        snapshot_id = recorded["snapshotId"]
        assert store.get_by_id(snapshot_id) == recorded
        converted = store.pricing_snapshot(snapshot_id, provider_id="vendor", model_id="m")
        assert converted is not None
        assert converted["id"] == snapshot_id
        assert converted["source"] == "dated-provider-price-page"
        assert converted["sourceDate"] == "2026-09-01"
        assert converted["recordedAt"] == recorded["recordedAt"]
        assert converted["effectiveAt"] == recorded["effective_at"]
        assert converted["expiresAt"] == recorded["expires_at"]
        assert converted["endpoint"] == recorded["endpoint"]
        assert converted["cacheRegime"] == "default"
        assert converted["contractedRatePerMillion"] == "8"
        assert converted["ratesPerMillion"] == {
            "inputUncached": 10.0, "cacheRead": 1.0,
            "cacheWrite": 20.0, "output": 30.0,
        }
        assert price_usage(usage(snapshot_id), converted)["modeledCostUsd"] == pytest.approx(
            0.0125
        )
        analysis = analyze_task([event(snapshot_id)], prices={snapshot_id: converted},
                                coverage_complete=True)
        assert analysis["currentModeledCostUsd"] == pytest.approx(0.0125)


def test_missing_currency_or_identity_mismatch_stays_unavailable(tmp_path):
    with PriceStore(tmp_path / "prices.sqlite") as store:
        usd_id = store.record(snapshot())["snapshotId"]
        eur_id = store.record(snapshot(currency="EUR"))["snapshotId"]
        assert store.get_by_id("missing") is None
        assert store.pricing_snapshot("missing", provider_id="vendor", model_id="m") is None
        assert store.pricing_snapshot(eur_id, provider_id="vendor", model_id="m") is None
        assert store.pricing_snapshot(usd_id, provider_id="other", model_id="m") is None
        assert store.pricing_snapshot(usd_id, provider_id="vendor", model_id="other") is None
        assert analyze_task([event(eur_id)], prices={}, coverage_complete=True)[
            "currentModeledCostUsd"
        ] is None
        with pytest.raises(ValueError, match="Snapshot ID is required"):
            store.get_by_id("")


def test_unknown_cache_rate_and_expiry_are_preserved(tmp_path):
    with PriceStore(tmp_path / "prices.sqlite") as store:
        rates = {"inputUncached": Decimal("10"), "cacheRead": None,
                 "cacheWrite": Decimal("20"), "output": Decimal("30")}
        snapshot_id = store.record(snapshot(rates_per_million=rates))["snapshotId"]
        converted = store.pricing_snapshot(snapshot_id, provider_id="vendor", model_id="m")
        assert converted is not None
        assert converted["ratesPerMillion"]["cacheRead"] is None
        assert price_usage(usage(snapshot_id), converted)["modeledCostUsd"] is None
        assert price_usage(usage(snapshot_id, cache_read_tokens=0), converted)[
            "modeledCostUsd"
        ] == pytest.approx(0.017)
        assert price_usage({**usage(snapshot_id), "occurredAt": "2026-10-01T00:00:00Z"},
                           converted)["modeledCostUsd"] is None


@pytest.mark.parametrize("rate", [Decimal("1e1000"), Decimal("1e-1000")])
def test_unrepresentable_rates_do_not_become_infinite_or_zero(tmp_path, rate):
    with PriceStore(tmp_path / "prices.sqlite") as store:
        rates = {"inputUncached": rate, "cacheRead": Decimal("1"),
                 "cacheWrite": Decimal("1"), "output": Decimal("1")}
        snapshot_id = store.record(snapshot(rates_per_million=rates))["snapshotId"]
        assert store.pricing_snapshot(snapshot_id, provider_id="vendor", model_id="m") is None
