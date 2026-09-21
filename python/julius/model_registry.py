"""Append-only local model facts, scoped to the endpoint that observed them."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


ModelState = Literal[
    "installed", "loaded", "available_remote", "unavailable", "unknown"
]


class ModelSnapshot(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    endpoint: str
    provider: str
    requested_model: str
    responded_model: str | None = None
    alias: str | None = None
    digest: str | None = None
    quantization: str | None = None
    tokenizer: str | None = None
    template: str | None = None
    context_window: int | None = Field(default=None, gt=0)
    tool_capabilities: dict[str, bool | None] = Field(default_factory=dict)
    state: ModelState = "unknown"
    source: str
    source_updated_at: datetime | None = None

    @field_validator("endpoint", "provider", "requested_model", "source")
    @classmethod
    def required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Required model identity field is empty")
        return value

    @field_validator("source_updated_at")
    @classmethod
    def aware_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Source update timestamp needs timezone")
        return value


def _identity(snapshot: ModelSnapshot) -> str:
    parts = [snapshot.endpoint, snapshot.provider, snapshot.requested_model,
             snapshot.responded_model, snapshot.digest, snapshot.quantization]
    raw = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ModelRegistry:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS model_snapshots (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id TEXT NOT NULL UNIQUE,
            identity_id TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            requested_model TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            body TEXT NOT NULL
        )""")
        self.db.execute("""CREATE INDEX IF NOT EXISTS model_snapshots_lookup
            ON model_snapshots(endpoint, requested_model, sequence DESC)""")
        self.db.execute("""CREATE TRIGGER IF NOT EXISTS model_snapshots_no_update
            BEFORE UPDATE ON model_snapshots BEGIN SELECT RAISE(ABORT, 'immutable snapshot'); END""")
        self.db.execute("""CREATE TRIGGER IF NOT EXISTS model_snapshots_no_delete
            BEFORE DELETE ON model_snapshots BEGIN SELECT RAISE(ABORT, 'immutable snapshot'); END""")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> ModelRegistry:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def add(self, snapshot: ModelSnapshot) -> dict[str, object]:
        if not isinstance(snapshot, ModelSnapshot):
            raise TypeError("Expected ModelSnapshot")
        record: dict[str, object] = {
            "snapshotId": str(uuid4()),
            "identityId": _identity(snapshot),
            "observedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            **snapshot.model_dump(mode="json"),
        }
        with self.db:
            self.db.execute(
                "INSERT INTO model_snapshots(snapshot_id,identity_id,endpoint,requested_model,observed_at,body) VALUES(?,?,?,?,?,?)",
                (record["snapshotId"], record["identityId"], snapshot.endpoint,
                 snapshot.requested_model, record["observedAt"],
                 json.dumps(record, ensure_ascii=False, separators=(",", ":"))),
            )
        return record

    def history(self, *, endpoint: str, requested_model: str) -> list[dict[str, object]]:
        rows = self.db.execute(
            "SELECT body FROM model_snapshots WHERE endpoint=? AND requested_model=? ORDER BY sequence",
            (endpoint, requested_model),
        ).fetchall()
        return [json.loads(row["body"]) for row in rows]

    def latest(self, *, endpoint: str, requested_model: str) -> dict[str, object] | None:
        row = self.db.execute(
            "SELECT body FROM model_snapshots WHERE endpoint=? AND requested_model=? ORDER BY sequence DESC LIMIT 1",
            (endpoint, requested_model),
        ).fetchone()
        return json.loads(row["body"]) if row is not None else None
