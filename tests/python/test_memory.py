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
