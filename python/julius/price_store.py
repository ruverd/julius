"""Append-only, dated local price evidence with explicit lookup outcomes."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, field_validator

RATE_KEYS = frozenset({"inputUncached", "cacheRead", "cacheWrite", "output"})


class PriceSnapshot(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    endpoint: str
    provider: str
    model: str
    currency: str
    tier: str
    cache_regime: str
    source: str
    source_date: date
    effective_at: datetime
    expires_at: datetime | None = None
    rates_per_million: dict[str, Decimal | None]
    contracted_rate_per_million: Decimal | None = None

    @field_validator("endpoint", "provider", "model", "tier", "cache_regime", "source")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Required price identity field is empty")
        return value

    @field_validator("currency")
    @classmethod
    def currency_code(cls, value: str) -> str:
        if len(value) != 3 or not value.isascii() or not value.isalpha() or not value.isupper():
            raise ValueError("Currency must be an uppercase three-letter code")
        return value

    @field_validator("effective_at", "expires_at")
    @classmethod
    def aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Price time needs timezone")
        return value

    @field_validator("rates_per_million")
    @classmethod
    def rates(cls, value: dict[str, Decimal | None]) -> dict[str, Decimal | None]:
        if set(value) != RATE_KEYS:
            raise ValueError("All four rate categories are required")
        if any(rate is not None and (not rate.is_finite() or rate < 0) for rate in value.values()):
            raise ValueError("Rates must be finite and nonnegative")
        return value

    @field_validator("contracted_rate_per_million")
    @classmethod
    def contracted_rate(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (not value.is_finite() or value < 0):
            raise ValueError("Contracted rate must be finite and nonnegative")
        return value

    def model_post_init(self, __context: Any) -> None:
        if self.expires_at is not None and self.expires_at <= self.effective_at:
            raise ValueError("Expiry must follow effective time")


class PriceStore:
    def __init__(self, path: str | Path):
        database_path = Path(path)
        if database_path.is_symlink():
            raise ValueError("Price store path is a symlink")
        try:
            fd = os.open(database_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                         getattr(os, "O_NOFOLLOW", 0), 0o600)
        except FileExistsError:
            info = database_path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise ValueError("Price store file has unsafe permissions")
        else:
            os.close(fd)
        self.db = sqlite3.connect(database_path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS price_snapshots (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id TEXT NOT NULL UNIQUE,
            endpoint TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            currency TEXT NOT NULL,
            tier TEXT NOT NULL,
            cache_regime TEXT NOT NULL,
            body TEXT NOT NULL
        )""")
        self.db.execute("""CREATE INDEX IF NOT EXISTS price_snapshots_lookup
            ON price_snapshots(endpoint,provider,model,currency,tier,cache_regime)""")
        self.db.execute("""CREATE TRIGGER IF NOT EXISTS price_snapshots_no_update
            BEFORE UPDATE ON price_snapshots BEGIN SELECT RAISE(ABORT, 'immutable snapshot'); END""")
        self.db.execute("""CREATE TRIGGER IF NOT EXISTS price_snapshots_no_delete
            BEFORE DELETE ON price_snapshots BEGIN SELECT RAISE(ABORT, 'immutable snapshot'); END""")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> PriceStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def record(self, snapshot: PriceSnapshot) -> dict[str, Any]:
        if not isinstance(snapshot, PriceSnapshot):
            raise TypeError("Expected PriceSnapshot")
        record = {"snapshotId": str(uuid4()),
                  "recordedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                  **snapshot.model_dump(mode="json")}
        with self.db:
            self.db.execute(
                "INSERT INTO price_snapshots(snapshot_id,endpoint,provider,model,currency,tier,cache_regime,body) VALUES(?,?,?,?,?,?,?,?)",
                (record["snapshotId"], snapshot.endpoint, snapshot.provider, snapshot.model,
                 snapshot.currency, snapshot.tier, snapshot.cache_regime,
                 json.dumps(record, separators=(",", ":"))),
            )
        return record

    def history(self, *, endpoint: str, provider: str, model: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT body FROM price_snapshots WHERE endpoint=? AND provider=? AND model=? ORDER BY sequence",
            (endpoint, provider, model),
        ).fetchall()
        return [json.loads(row["body"]) for row in rows]

    def lookup(
        self, *, endpoint: str, provider: str, model: str, currency: str,
        tier: str, cache_regime: str, at: datetime,
    ) -> dict[str, Any]:
        if not isinstance(at, datetime) or at.tzinfo is None:
            raise ValueError("Lookup time needs timezone")
        rows = self.db.execute(
            "SELECT body FROM price_snapshots WHERE endpoint=? AND provider=? AND model=? AND currency=? AND tier=? AND cache_regime=?",
            (endpoint, provider, model, currency, tier, cache_regime),
        ).fetchall()
        matched = []
        for row in rows:
            record = json.loads(row["body"])
            start = datetime.fromisoformat(record["effective_at"].replace("Z", "+00:00"))
            end_raw = record["expires_at"]
            end = datetime.fromisoformat(end_raw.replace("Z", "+00:00")) if end_raw else None
            if start <= at and (end is None or at < end):
                matched.append(record)
        if not matched:
            return {"status": "unknown", "snapshot": None, "candidateIds": []}
        if len(matched) > 1:
            return {"status": "ambiguous", "snapshot": None,
                    "candidateIds": [item["snapshotId"] for item in matched]}
        return {"status": "known", "snapshot": matched[0],
                "candidateIds": [matched[0]["snapshotId"]]}
