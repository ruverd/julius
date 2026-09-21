from datetime import datetime, timedelta, timezone
import hashlib
import sqlite3

import pytest

from julius.memory import MemoryStore


def memory(**changes):
    text = changes.pop("content", "Compiler error in dependency graph")
    now = datetime.now(timezone.utc)
    result = {
        "id": "fact",
        "version": 1,
        "projectId": "one",
        "snapshot": "commit-a",
        "content": text,
        "contentSha256": hashlib.sha256(text.encode()).hexdigest(),
        "createdAt": (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        "expiresAt": (now + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        "provenance": "observed",
        "origin": "log:17",
    }
    return {**result, **changes}


def test_project_snapshot_expiry_and_invalidation(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    try:
        store.put(memory())
        store.put(memory(projectId="two"))
        assert len(store.search("one", "compiler", snapshot="commit-a")) == 1
        assert store.search("one", "compiler", snapshot="commit-b") == []
        assert store.invalidate("fact", "one") == 1
        assert store.search("one", "compiler", snapshot="commit-a") == []
        assert len(store.search("two", "compiler", snapshot="commit-a")) == 1
        store.put(
            memory(
                id="old",
                expiresAt=(datetime.now(timezone.utc) - timedelta(milliseconds=1))
                .isoformat()
                .replace("+00:00", "Z"),
            )
        )
        assert store.purge_expired("one") == 1
        assert store.delete_project("two") == 1
    finally:
        store.close()


def test_hash_and_literal_query():
    store = MemoryStore(":memory:")
    try:
        store.put(memory())
        with pytest.raises(ValueError, match="hash"):
            store.put(memory(id="bad", contentSha256="bad"))
        assert store.search("one", '" OR *', snapshot="commit-a") == []
    finally:
        store.close()


def test_tampering_and_symlink_path_are_rejected(tmp_path):
    path = tmp_path / "memory.db"
    store = MemoryStore(path)
    try:
        store.put(memory())
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "UPDATE memories SET content=? WHERE id=?",
                ("Compiler error in altered graph", "fact"),
            )
            connection.commit()
        finally:
            connection.close()
        with pytest.raises(ValueError, match="integrity"):
            store.search("one", "compiler", snapshot="commit-a")
    finally:
        store.close()
    link = tmp_path / "link.db"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="Unsafe"):
        MemoryStore(link)


def test_three_and_six_digit_utc_dates_store_canonical_milliseconds():
    store = MemoryStore(":memory:")
    try:
        now = datetime.now(timezone.utc)
        past = (
            (now - timedelta(seconds=2)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        )
        future = (
            (now + timedelta(seconds=30)).isoformat(timespec="microseconds").replace("+00:00", "Z")
        )
        store.put(memory(createdAt=past, expiresAt=future))
        row = store.db.execute(
            "SELECT created_at,expires_at FROM memories WHERE id='fact'"
        ).fetchone()
        assert row is not None
        assert row[0] == past
        assert len(row[1]) == 24
        assert len(store.search("one", "compiler", snapshot="commit-a")) == 1
        expired = (
            (now - timedelta(milliseconds=1))
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
        store.put(memory(id="expired", createdAt=past, expiresAt=expired))
        assert store.purge_expired("one") == 1
        with pytest.raises(ValueError, match="expiry"):
            store.put(memory(id="bad-date", createdAt=past, expiresAt="2026-01-01T00:00:00Z"))
    finally:
        store.close()


def test_confidence_and_invalidation_audit_are_project_scoped():
    store = MemoryStore(":memory:")
    try:
        store.put(memory(confidence=0.7, invalidationCondition="dependency changes"))
        store.put(memory(projectId="two"))
        hit = store.search("one", "compiler", snapshot="commit-a")[0]
        assert hit["confidence"] == 0.7
        assert hit["invalidationCondition"] == "dependency changes"
        assert store.invalidate("fact", "one", reason="dependency changed", source="watcher") == 1
        assert store.invalidate("fact", "one", reason="later") == 0
        row = store.db.execute(
            "SELECT invalidated_at,invalidation_reason,invalidation_source "
            "FROM memories WHERE project_id='one'"
        ).fetchone()
        assert row is not None
        assert row[0].endswith("Z")
        assert row[1:] == ("dependency changed", "watcher")
        assert store.search("one", "compiler", snapshot="commit-a") == []
        assert store.search("two", "compiler", snapshot="commit-a")[0]["confidence"] is None
    finally:
        store.close()


@pytest.mark.parametrize("confidence", [-0.1, 1.1, True, float("nan"), float("inf"), "0.5"])
def test_invalid_confidence_rejected(confidence):
    store = MemoryStore(":memory:")
    try:
        with pytest.raises(ValueError, match="confidence"):
            store.put(memory(confidence=confidence))
    finally:
        store.close()


def test_legacy_schema_migrates_without_inventing_audit_values(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE memories (id TEXT, version INTEGER, project_id TEXT, snapshot TEXT,
                content TEXT, content_sha256 TEXT, created_at TEXT, expires_at TEXT,
                provenance TEXT, origin TEXT, invalidated INTEGER DEFAULT 0,
                PRIMARY KEY(project_id,id,version));
        """)
        item = memory()
        db.execute(
            "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            tuple(item[key] for key in (
                "id", "version", "projectId", "snapshot", "content", "contentSha256",
                "createdAt", "expiresAt", "provenance", "origin",
            )) + (1,),
        )
    store = MemoryStore(path)
    try:
        row = store.db.execute(
            "SELECT confidence,invalidation_condition,invalidated_at,invalidation_reason,"
            "invalidation_source FROM memories WHERE id='fact'"
        ).fetchone()
        assert row == (None, None, None, None, None)
        assert store.invalidate("fact", "one") == 0
        legacy = store.history("one", "fact")[0]
        assert legacy["invalidated"] is True
        assert legacy["invalidatedAt"] is None
        assert legacy["invalidationReason"] is None
        assert legacy["invalidationSource"] is None
        store.put(memory(id="new"))
        assert store.search("one", "compiler", snapshot="commit-a")[0]["id"] == "new"
    finally:
        store.close()


def test_history_is_bounded_project_scoped_and_content_free():
    store = MemoryStore(":memory:")
    try:
        store.put(memory(id="a", version=1, content="secret text compiler"))
        store.put(memory(id="a", version=2, content="new secret compiler"))
        store.put(memory(id="b", projectId="two", content="other secret compiler"))
        assert store.invalidate("a", "one", reason="stale", source="test") == 2
        rows = store.history("one", "a")
        assert [row["version"] for row in rows] == [2, 1]
        assert all("content" not in row for row in rows)
        assert all(row["invalidationReason"] == "stale" for row in rows)
        assert all(row["invalidationSource"] == "test" for row in rows)
        assert len(store.history("one", limit=1)) == 1
        assert store.history("one", "b") == []
        assert store.history("two")[0]["id"] == "b"
        for invalid in ("", 4):
            with pytest.raises(ValueError):
                store.history(invalid)
        for invalid in ("", 4):
            with pytest.raises(ValueError):
                store.history("one", invalid)
        for invalid in (0, 101, True, 1.5):
            with pytest.raises(ValueError):
                store.history("one", limit=invalid)
        for invalid in (-1, True, 1.5, "0"):
            with pytest.raises(ValueError):
                store.history("one", offset=invalid)
    finally:
        store.close()


def test_history_offset_pages_cover_more_than_one_hundred_records():
    store = MemoryStore(":memory:")
    try:
        for index in range(205):
            store.put(memory(id=f"fact-{index:03d}", content=f"secret {index}"))
        store.put(memory(id="other-project", projectId="two"))
        pages = [store.history("one", limit=100, offset=offset) for offset in (0, 100, 200)]
        ids = [row["id"] for page in pages for row in page]
        assert [len(page) for page in pages] == [100, 100, 5]
        assert len(ids) == len(set(ids)) == 205
        assert set(ids) == {f"fact-{index:03d}" for index in range(205)}
        assert all(row["projectId"] == "one" and "content" not in row for page in pages for row in page)
        assert store.history("one", offset=205) == []
    finally:
        store.close()
