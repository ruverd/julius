"""Transactional SQLite audit log and decision store for quality suspension."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .quality_guard import GuardPolicy, ManualAction, Scope, TaskOutcome, decide_suspension


class QualityStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS quality_records (
                scope_key TEXT NOT NULL, sequence INTEGER NOT NULL,
                kind TEXT NOT NULL, body TEXT NOT NULL,
                PRIMARY KEY (scope_key, sequence)
            );
            CREATE TABLE IF NOT EXISTS quality_decisions (
                scope_key TEXT PRIMARY KEY, policy_version TEXT NOT NULL,
                decision TEXT NOT NULL
            );
        """)

    @staticmethod
    def _key(scope: Scope) -> str:
        return scope.model_dump_json()

    def _records(self, scope: Scope) -> tuple[list[TaskOutcome], list[ManualAction]]:
        rows = self.db.execute(
            "SELECT kind, body FROM quality_records WHERE scope_key=? ORDER BY sequence",
            (self._key(scope),),
        ).fetchall()
        outcomes: list[TaskOutcome] = []
        actions: list[ManualAction] = []
        for kind, body in rows:
            if kind == "outcome":
                outcomes.append(TaskOutcome.model_validate_json(body))
            elif kind == "manual":
                actions.append(ManualAction.model_validate_json(body))
            else:
                raise ValueError("Unknown quality record kind")
        return outcomes, actions

    def _decide(self, scope: Scope, policy: GuardPolicy) -> dict[str, Any]:
        outcomes, actions = self._records(scope)
        decision = decide_suspension(scope, policy, outcomes, actions)
        self.db.execute(
            "INSERT INTO quality_decisions(scope_key,policy_version,decision) VALUES(?,?,?) "
            "ON CONFLICT(scope_key) DO UPDATE SET policy_version=excluded.policy_version, "
            "decision=excluded.decision",
            (self._key(scope), policy.version, json.dumps(decision, allow_nan=False)),
        )
        return decision

    def decision(self, scope: Scope, policy: GuardPolicy) -> dict[str, Any]:
        """Recompute under a write lock; policy changes cannot reuse stale clearance."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            result = self._decide(scope, policy)
            self.db.execute("COMMIT")
            return result
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def append(self, record: TaskOutcome | ManualAction, policy: GuardPolicy) -> dict[str, Any]:
        """Commit an audit record and its resulting decision atomically."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            latest = self.db.execute(
                "SELECT MAX(sequence) FROM quality_records WHERE scope_key=?",
                (self._key(record.scope),),
            ).fetchone()[0]
            if latest is not None and record.sequence <= latest:
                raise ValueError("Quality record sequence must increase")
            self.db.execute(
                "INSERT INTO quality_records(scope_key,sequence,kind,body) VALUES(?,?,?,?)",
                (self._key(record.scope), record.sequence,
                 "outcome" if isinstance(record, TaskOutcome) else "manual",
                 record.model_dump_json()),
            )
            result = self._decide(record.scope, policy)
            self.db.execute("COMMIT")
            return result
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def history(self, scope: Scope) -> dict[str, Any]:
        """Return persisted inputs and the most recently committed decision."""
        outcomes, actions = self._records(scope)
        row = self.db.execute(
            "SELECT decision FROM quality_decisions WHERE scope_key=?", (self._key(scope),),
        ).fetchone()
        return {
            "outcomes": [item.model_dump() for item in outcomes],
            "actions": [item.model_dump() for item in actions],
            "decision": json.loads(row[0]) if row else None,
        }

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> QualityStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
