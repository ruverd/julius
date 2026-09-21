from datetime import date, datetime, timezone
from decimal import Decimal
import sqlite3

import pytest
from pydantic import ValidationError

from julius.price_store import PriceSnapshot, PriceStore


T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
T1 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def snapshot(**changes):
    values = {
        "endpoint": "https://api.example.test/v1", "provider": "example",
        "model": "model-a", "currency": "USD", "tier": "standard",
        "cache_regime": "default", "source": "provider-price-page",
        "source_date": date(2026, 8, 20), "effective_at": T0,
        "rates_per_million": {"inputUncached": Decimal("1.25"),
                              "cacheRead": None, "cacheWrite": None,
                              "output": Decimal("4.50")},
    }
    values.update(changes)
    return PriceSnapshot(**values)


def lookup(store, **changes):
    args = {"endpoint": "https://api.example.test/v1", "provider": "example",
            "model": "model-a", "currency": "USD", "tier": "standard",
            "cache_regime": "default", "at": T0}
    args.update(changes)
    return store.lookup(**args)


def test_dated_lookup_preserves_source_and_unknown_rates(tmp_path):
    with PriceStore(tmp_path / "prices.sqlite") as store:
        item = store.record(snapshot(expires_at=T1, contracted_rate_per_million=Decimal("0.90")))
        assert lookup(store)["snapshot"] == item
        assert item["source_date"] == "2026-08-20"
        assert item["rates_per_million"]["cacheRead"] is None
        assert item["contracted_rate_per_million"] == "0.90"
        assert lookup(store, at=T1)["status"] == "unknown"
        assert lookup(store, endpoint="https://other.example.test/v1")["status"] == "unknown"
        assert lookup(store, tier="batch")["status"] == "unknown"
        assert store.history(endpoint=item["endpoint"], provider="example", model="model-a") == [item]


def test_overlapping_snapshots_are_explicitly_ambiguous(tmp_path):
    with PriceStore(tmp_path / "prices.sqlite") as store:
        first = store.record(snapshot())
        second = store.record(snapshot(source="contract", source_date=date(2026, 9, 2)))
        result = lookup(store)
        assert result["status"] == "ambiguous"
        assert result["snapshot"] is None
        assert result["candidateIds"] == [first["snapshotId"], second["snapshotId"]]


def test_strict_rates_dates_and_file_immutability(tmp_path):
    with pytest.raises(ValidationError):
        snapshot(rates_per_million={"output": Decimal("1")})
    with pytest.raises(ValidationError):
        snapshot(rates_per_million={"inputUncached": Decimal("NaN"),
                                    "cacheRead": None, "cacheWrite": None,
                                    "output": Decimal("1")})
    with pytest.raises(ValidationError):
        snapshot(effective_at=datetime(2026, 9, 1))
    with pytest.raises(ValidationError):
        snapshot(expires_at=T0)
    path = tmp_path / "prices.sqlite"
    with PriceStore(path) as store:
        item = store.record(snapshot())
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            store.db.execute("DELETE FROM price_snapshots WHERE snapshot_id=?",
                             (item["snapshotId"],))
    assert path.stat().st_mode & 0o077 == 0
