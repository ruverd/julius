"""SQLite WAL event ledger and atomic, crash-expiring budget reservations."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from .events import normalize_utc, validate_event


def _safe_path(path: str | Path) -> str:
    if str(path) == ":memory:":
        return ":memory:"
    target = Path(path).absolute()
    parts = target.parent.parts
    current = Path(parts[0])
    # Resolve the OS-owned first component, including macOS /var -> /private/var.
    if len(parts) > 1:
        current = (current / parts[1]).resolve(strict=True)
    for part in parts[2:]:
        current /= part
        if current.is_symlink():
            raise ValueError("Unsafe ledger parent")
        if not current.exists():
            current.mkdir(mode=0o700)
        if not current.is_dir():
            raise ValueError("Unsafe ledger parent")
    target = current / target.name
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ValueError("Unsafe ledger path")
    return str(target)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _retry_locked(action: Callable[[], Any]) -> Any:
    """Retry SQLite startup locks while other processes enable WAL or create schema."""
    deadline = time.monotonic() + 5
    while True:
        try:
            return action()
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or time.monotonic() >= deadline:
                raise
            time.sleep(0.025)


class Ledger:
    def __init__(self, path: str | Path):
        safe = _safe_path(path)
        self.db = sqlite3.connect(safe, timeout=5.0, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        if safe != ":memory:":
            os.chmod(safe, stat.S_IRUSR | stat.S_IWUSR)
        self.db.execute("PRAGMA busy_timeout=5000")
        try:
            _retry_locked(lambda: self.db.execute("PRAGMA journal_mode=WAL"))
            _retry_locked(lambda: self.db.executescript("""
            CREATE TABLE IF NOT EXISTS events (
              event_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_event_id TEXT NOT NULL,
              project_id TEXT NOT NULL, task_id TEXT, model_id TEXT, event_type TEXT NOT NULL,
              occurred_at TEXT NOT NULL, call_id TEXT, body TEXT NOT NULL,
              UNIQUE(source_id,source_event_id));
            CREATE INDEX IF NOT EXISTS events_time ON events(occurred_at);
            CREATE INDEX IF NOT EXISTS events_project_time ON events(project_id,occurred_at);
            CREATE INDEX IF NOT EXISTS events_task_time ON events(task_id,occurred_at);
            CREATE INDEX IF NOT EXISTS events_model_time ON events(model_id,occurred_at);
            CREATE INDEX IF NOT EXISTS events_call_project ON events(call_id,project_id);
            CREATE TABLE IF NOT EXISTS event_aliases (
              event_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_event_id TEXT NOT NULL,
              canonical_event_id TEXT NOT NULL, body TEXT NOT NULL,
              UNIQUE(source_id,source_event_id));
            CREATE TABLE IF NOT EXISTS budgets (budget_id TEXT PRIMARY KEY, limit_amount REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS reservations (
              reservation_id TEXT PRIMARY KEY, budget_id TEXT NOT NULL, amount REAL NOT NULL,
              limit_amount REAL NOT NULL, spent REAL, expires_at TEXT NOT NULL, status TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS reservations_budget ON reservations(budget_id,status,expires_at);
            """))
        except BaseException:
            self.db.close()
            raise

    @contextmanager
    def _write(self) -> Iterator[None]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        else:
            self.db.execute("COMMIT")

    def record(self, input: dict[str, Any]) -> dict[str, Any]:
        event = validate_event(input)
        with self._write():
            return self._record_validated(event)

    def record_many(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        validated = [validate_event(event) for event in events]
        with self._write():
            return [self._record_validated(event) for event in validated]

    def record_generated_event(self, input: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Atomically reuse the first timestamp for an internally generated source ID."""
        event = validate_event(input)
        with self._write():
            existing = self.db.execute(
                "SELECT body FROM events WHERE source_id=? AND source_event_id=?",
                (event["sourceId"], event["sourceEventId"]),
            ).fetchone()
            if existing:
                prior = validate_event(json.loads(existing["body"]))
                event = {**event, "occurredAt": prior["occurredAt"]}
            return event, self._record_validated(event)

    def record_generated_pair(
        self, generated: dict[str, Any], companion: dict[str, Any]
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Record a generated event and its companion under one SQLite write lock."""
        event = validate_event(generated)
        other = validate_event(companion)
        with self._write():
            existing = self.db.execute(
                "SELECT body FROM events WHERE source_id=? AND source_event_id=?",
                (event["sourceId"], event["sourceEventId"]),
            ).fetchone()
            if existing:
                prior = validate_event(json.loads(existing["body"]))
                event = {**event, "occurredAt": prior["occurredAt"]}
            receipts = [self._record_validated(event), self._record_validated(other)]
            return event, receipts

    def _record_validated(self, event: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(event, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
        existing = self.db.execute(
            """SELECT event_id,body FROM events WHERE source_id=? AND source_event_id=?
            UNION ALL SELECT canonical_event_id,body FROM event_aliases WHERE source_id=? AND source_event_id=?""",
            (
                event["sourceId"],
                event["sourceEventId"],
                event["sourceId"],
                event["sourceEventId"],
            ),
        ).fetchone()
        if existing:
            if validate_event(json.loads(existing["body"])) != event:
                raise ValueError("Conflicting source event")
            return {
                "eventId": existing["event_id"],
                "inserted": False,
                "duplicateOf": existing["event_id"],
            }
        collision = self.db.execute(
            "SELECT 1 FROM events WHERE event_id=? UNION ALL SELECT 1 FROM event_aliases WHERE event_id=?",
            (event["eventId"], event["eventId"]),
        ).fetchone()
        if collision:
            raise ValueError("Conflicting event ID")
        payload = event["payload"]
        if event["eventType"] == "reconciliation":
            row = self.db.execute(
                "SELECT body FROM events WHERE event_id=?", (payload["targetEventId"],)
            ).fetchone()
            target = validate_event(json.loads(row["body"])) if row else None
            if (
                target is None
                or target["eventType"] != "usage"
                or any(
                    target[key] != event[key]
                    for key in (
                        "projectId",
                        "sessionId",
                        "requestId",
                        "attemptId",
                        "providerId",
                        "modelId",
                        "clientId",
                    )
                )
            ):
                raise ValueError("Reconciliation target must be an owned usage event")
        if event["eventType"] == "transform":
            prior_rows = self.db.execute(
                "SELECT body FROM events WHERE event_type='transform' AND project_id=?",
                (event["projectId"],),
            ).fetchall()
            prior_events = [validate_event(json.loads(row["body"])) for row in prior_rows]
            for prior in prior_events:
                old = prior["payload"]
                if old["transformId"] == payload["transformId"]:
                    raise ValueError("Duplicate transform ID")
                if (
                    payload["sent"]
                    and old["sent"]
                    and all(prior[key] == event[key] for key in ("requestId", "attemptId"))
                    and old["scope"] == payload["scope"]
                    and old["parentTransformId"] == payload["parentTransformId"]
                ):
                    raise ValueError("Multiple sent transforms for one branch")
                if old["transformId"] == payload["parentTransformId"] and (
                    prior["requestId"] != event["requestId"]
                    or prior["modelId"] != event["modelId"]
                    or old["tokenizer"] != payload["tokenizer"]
                    or old["outputTokens"] != payload["inputTokens"]
                ):
                    raise ValueError("Transform chain mismatch")
            if payload["parentTransformId"] is not None and not any(
                p["payload"]["transformId"] == payload["parentTransformId"] for p in prior_events
            ):
                raise ValueError("Missing parent transform")
        call_id = payload["callId"] if event["eventType"] == "usage" else None
        if call_id is not None:
            row = self.db.execute(
                "SELECT event_id,body FROM events WHERE call_id=? AND project_id=? AND event_type='usage' ORDER BY rowid LIMIT 1",
                (call_id, event["projectId"]),
            ).fetchone()
            if row:
                prior = validate_event(json.loads(row["body"]))
                same_call = (
                    all(
                        prior[key] == event[key] for key in ("requestId", "attemptId", "providerId")
                    )
                    and prior["payload"]["category"] == payload["category"]
                )
                if same_call:
                    same_identity = all(
                        prior[key] == event[key] for key in ("sessionId", "clientId", "modelId")
                    )
                    measured = (
                        "inputTokens",
                        "outputTokens",
                        "cacheReadTokens",
                        "cacheWriteTokens",
                        "complete",
                        "tokenizerId",
                        "tokenizerSource",
                        "costUsd",
                        "costProvenance",
                        "observationScope",
                    )
                    same_measurement = all(
                        prior["payload"].get(key) == payload.get(key) for key in measured
                    )
                    if not same_identity or not same_measurement:
                        raise ValueError("Conflicting call measurements; reconciliation required")
                    self.db.execute(
                        "INSERT INTO event_aliases VALUES (?,?,?,?,?)",
                        (
                            event["eventId"],
                            event["sourceId"],
                            event["sourceEventId"],
                            row["event_id"],
                            body,
                        ),
                    )
                    return {
                        "eventId": event["eventId"],
                        "inserted": False,
                        "duplicateOf": row["event_id"],
                    }
        self.db.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                event["eventId"],
                event["sourceId"],
                event["sourceEventId"],
                event["projectId"],
                event["taskId"],
                event["modelId"],
                event["eventType"],
                event["occurredAt"],
                call_id,
                body,
            ),
        )
        return {"eventId": event["eventId"], "inserted": True, "duplicateOf": None}

    def history(self, filters: dict[str, str] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        columns = {
            "projectId": "project_id",
            "taskId": "task_id",
            "modelId": "model_id",
            "eventType": "event_type",
        }
        clauses: list[str] = []
        args: list[str] = []
        for key, column in columns.items():
            if key in filters:
                clauses.append(f"{column}=?")
                args.append(filters[key])
        if "since" in filters:
            clauses.append("occurred_at>=?")
            args.append(normalize_utc(filters["since"]))
        if "until" in filters:
            clauses.append("occurred_at<?")
            args.append(normalize_utc(filters["until"]))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.db.execute(
            "SELECT body FROM events" + where + " ORDER BY occurred_at,event_id", args
        ).fetchall()
        return [validate_event(json.loads(row["body"])) for row in rows]

    def export_history(self, filters: dict[str, str] | None = None) -> list[dict[str, Any]]:
        """Return raw, replayable events selected by scope and occurrence time.

        Reconciliations and source aliases of selected usage events are included
        even when their own timestamps fall outside the requested window.
        Transform ancestors are included when needed for replay validation.
        """
        filters = filters or {}
        since = normalize_utc(filters["since"]) if "since" in filters else None
        until = normalize_utc(filters["until"]) if "until" in filters else None
        rows = self.db.execute("SELECT event_id,body FROM events ORDER BY rowid").fetchall()
        events = [validate_event(json.loads(row["body"])) for row in rows]
        selected: set[str] = set()
        transforms: dict[tuple[str, str], dict[str, Any]] = {}

        for event in events:
            if event["eventType"] == "transform":
                transforms[(event["projectId"], event["payload"]["transformId"])] = event
            if event["eventType"] == "reconciliation":
                continue
            if any(
                event[key] != filters[key]
                for key in ("projectId", "taskId", "modelId")
                if key in filters
            ):
                continue
            if since is not None and event["occurredAt"] < since:
                continue
            if until is not None and event["occurredAt"] >= until:
                continue
            if "eventType" in filters and event["eventType"] != filters["eventType"]:
                continue
            selected.add(event["eventId"])

        # A transform may precede the time window while its child is selected.
        pending = [event for event in events if event["eventId"] in selected]
        while pending:
            event = pending.pop()
            if event["eventType"] != "transform":
                continue
            parent_id = event["payload"]["parentTransformId"]
            if parent_id is None:
                continue
            parent = transforms[(event["projectId"], parent_id)]
            if parent["eventId"] not in selected:
                selected.add(parent["eventId"])
                pending.append(parent)

        exported = []
        for event in events:
            if event["eventId"] in selected or (
                event["eventType"] == "reconciliation"
                and event["payload"]["targetEventId"] in selected
            ):
                exported.append(event)

        # Aliases live in a separate table. They can be replayed after their
        # canonical event; their original position among events is not stored.
        for row in self.db.execute(
            "SELECT canonical_event_id,body FROM event_aliases ORDER BY rowid"
        ):
            if row["canonical_event_id"] in selected:
                exported.append(validate_event(json.loads(row["body"])))
        return exported

    def events(self, filters: dict[str, str] | None = None) -> list[dict[str, Any]]:
        history = self.history(filters)
        corrections: dict[str, list[dict[str, Any]]] = {}
        for row in self.db.execute(
            "SELECT body FROM events WHERE event_type='reconciliation' ORDER BY rowid"
        ):
            event = validate_event(json.loads(row["body"]))
            corrections.setdefault(event["payload"]["targetEventId"], []).append(event)
        effective = []
        for event in history:
            if event["eventType"] == "reconciliation":
                continue
            if event["eventType"] == "usage" and event["eventId"] in corrections:
                payload = dict(event["payload"])
                for correction in corrections[event["eventId"]]:
                    fix = correction["payload"]
                    for old, new in (
                        ("inputTokens", "effectiveInputTokens"),
                        ("outputTokens", "effectiveOutputTokens"),
                        ("cacheReadTokens", "effectiveCacheReadTokens"),
                        ("cacheWriteTokens", "effectiveCacheWriteTokens"),
                        ("costUsd", "effectiveCostUsd"),
                        ("costProvenance", "effectiveCostProvenance"),
                    ):
                        payload[old] = fix[new]
                    if fix["effectiveComplete"] is not None:
                        payload["complete"] = fix["effectiveComplete"]
                    if fix["effectiveTokenizerId"] is not None:
                        payload["tokenizerId"] = fix["effectiveTokenizerId"]
                        payload["tokenizerSource"] = fix["effectiveTokenizerSource"]
                event = {**event, "payload": payload}
            effective.append(event)
        return effective

    def reserve_budget(self, input: dict[str, Any]) -> bool:
        budget_id = input["budgetId"]
        reservation_id = input["reservationId"]
        amount = input["amount"]
        limit = input["limit"]
        expires = normalize_utc(input["expiresAt"])
        if (
            not isinstance(budget_id, str)
            or not budget_id.strip()
            or not isinstance(reservation_id, str)
            or not reservation_id.strip()
            or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v < float("inf")
                for v in (amount, limit)
            )
        ):
            raise ValueError("Invalid reservation")
        with self._write():
            budget = self.db.execute(
                "SELECT limit_amount FROM budgets WHERE budget_id=?", (budget_id,)
            ).fetchone()
            if budget and budget["limit_amount"] != limit:
                raise ValueError("Conflicting budget limit")
            if not budget:
                old_limits = self.db.execute(
                    "SELECT DISTINCT limit_amount FROM reservations WHERE budget_id=?", (budget_id,)
                ).fetchall()
                if len(old_limits) > 1 or (old_limits and old_limits[0]["limit_amount"] != limit):
                    raise ValueError("Conflicting budget limit")
                self.db.execute("INSERT INTO budgets VALUES (?,?)", (budget_id, limit))
            self.db.execute(
                "UPDATE reservations SET status='expired' WHERE status='reserved' AND expires_at<=?",
                (_now(),),
            )
            prior = self.db.execute(
                "SELECT * FROM reservations WHERE reservation_id=?", (reservation_id,)
            ).fetchone()
            if prior:
                if any(
                    prior[key] != value
                    for key, value in (
                        ("budget_id", budget_id),
                        ("amount", amount),
                        ("limit_amount", limit),
                        ("expires_at", expires),
                    )
                ):
                    raise ValueError("Conflicting reservation")
                return prior["status"] in ("reserved", "settled")
            if expires <= _now():
                return False
            used = self.db.execute(
                "SELECT COALESCE(SUM(CASE WHEN status='settled' THEN spent ELSE amount END),0) AS used FROM reservations WHERE budget_id=? AND status IN ('reserved','settled')",
                (budget_id,),
            ).fetchone()["used"]
            if used + amount > limit:
                return False
            self.db.execute(
                "INSERT INTO reservations VALUES (?,?,?,?,NULL,?,'reserved')",
                (reservation_id, budget_id, amount, limit, expires),
            )
            return True

    def settle_budget(self, reservation_id: str, actual_amount: float) -> None:
        if (
            isinstance(actual_amount, bool)
            or not isinstance(actual_amount, (int, float))
            or not 0 <= actual_amount < float("inf")
        ):
            raise ValueError("Invalid settlement")
        with self._write():
            row = self.db.execute(
                "SELECT status,spent,expires_at,amount FROM reservations WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
            if not row:
                raise ValueError("Unknown reservation")
            if row["status"] == "settled":
                if row["spent"] != actual_amount:
                    raise ValueError("Conflicting settlement")
                return
            if actual_amount > row["amount"]:
                raise ValueError("Settlement exceeds reservation")
            if row["status"] != "reserved" or row["expires_at"] <= _now():
                raise ValueError("Reservation inactive")
            self.db.execute(
                "UPDATE reservations SET status='settled',spent=? WHERE reservation_id=?",
                (actual_amount, reservation_id),
            )

    def release_budget(self, reservation_id: str) -> None:
        with self._write():
            self.db.execute(
                "UPDATE reservations SET status='released' WHERE reservation_id=? AND status='reserved'",
                (reservation_id,),
            )

    def close(self) -> None:
        self.db.close()
