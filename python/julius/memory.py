"""Local SQLite FTS5 memory, always scoped to an exact project snapshot."""

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import sqlite3


def _utc_millis(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}(?:\d{3})?Z", value
    ):
        raise ValueError("Invalid UTC timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError("Invalid UTC timestamp")
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _now_millis() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class MemoryStore:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            file = Path(path).absolute()
            parts = file.parent.parts
            current = Path(parts[0], parts[1]).resolve() if len(parts) > 1 else Path(parts[0])
            for part in parts[2:]:
                current /= part
                if current.is_symlink():
                    raise ValueError("Unsafe memory directory")
                current.mkdir(mode=0o700, exist_ok=True)
            file = current / file.name
            if file.is_symlink():
                raise ValueError("Unsafe memory path")
            path = file
        self.db = sqlite3.connect(str(path))
        if str(path) != ":memory:":
            Path(path).chmod(0o600)
        self.db.executescript("""PRAGMA journal_mode=WAL; PRAGMA secure_delete=ON;
            CREATE TABLE IF NOT EXISTS memories (id TEXT, version INTEGER, project_id TEXT, snapshot TEXT, content TEXT, content_sha256 TEXT, created_at TEXT, expires_at TEXT, provenance TEXT, origin TEXT, invalidated INTEGER DEFAULT 0, PRIMARY KEY(project_id,id,version));
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(content, content='memories', content_rowid='rowid');
            CREATE TRIGGER IF NOT EXISTS memory_ai AFTER INSERT ON memories BEGIN INSERT INTO memory_fts(rowid,content) VALUES(new.rowid,new.content); END;
            CREATE TRIGGER IF NOT EXISTS memory_ad AFTER DELETE ON memories BEGIN INSERT INTO memory_fts(memory_fts,rowid,content) VALUES('delete',old.rowid,old.content); END;""")

    def put(self, item: dict) -> None:
        if (
            not all(
                isinstance(item.get(key), str) and item[key]
                for key in ("id", "projectId", "snapshot", "origin")
            )
            or type(item.get("version")) is not int
            or item["version"] < 1
        ):
            raise ValueError("Invalid memory identity")
        content = item.get("content")
        if not isinstance(content, str) or len(content.encode()) > 1024 * 1024:
            raise ValueError("Invalid memory content")
        if hashlib.sha256(content.encode()).hexdigest() != item.get("contentSha256"):
            raise ValueError("Memory content hash mismatch")
        try:
            created = _utc_millis(item["createdAt"])
            expires = _utc_millis(item["expiresAt"])
            if expires <= created:
                raise ValueError
        except (KeyError, ValueError, AttributeError) as error:
            raise ValueError("Invalid memory expiry") from error
        if item.get("provenance") not in ("observed", "inferred", "user_confirmed"):
            raise ValueError("Invalid memory provenance")
        stored = {**item, "createdAt": created, "expiresAt": expires}
        with self.db:
            self.db.execute(
                "INSERT INTO memories(id,version,project_id,snapshot,content,content_sha256,created_at,expires_at,provenance,origin) VALUES(?,?,?,?,?,?,?,?,?,?)",
                tuple(
                    stored[key]
                    for key in (
                        "id",
                        "version",
                        "projectId",
                        "snapshot",
                        "content",
                        "contentSha256",
                        "createdAt",
                        "expiresAt",
                        "provenance",
                        "origin",
                    )
                ),
            )

    def search(self, project_id: str, query: str, *, snapshot: str, limit: int = 20) -> list[dict]:
        if not project_id or not snapshot:
            raise ValueError("Project and snapshot required")
        if (
            not isinstance(query, str)
            or len(query) > 256
            or type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise ValueError("Invalid query or limit")
        words = re.findall(r"\w+", query, re.UNICODE)[:16]
        if not words:
            return []
        expression = " AND ".join('"' + word.replace('"', '""') + '"' for word in words)
        rows = self.db.execute(
            """SELECT m.id,m.version,m.project_id,m.snapshot,m.content,m.content_sha256,m.created_at,m.expires_at,m.provenance,m.origin,bm25(memory_fts) FROM memory_fts JOIN memories m ON m.rowid=memory_fts.rowid WHERE memory_fts MATCH ? AND m.project_id=? AND m.snapshot=? AND m.invalidated=0 AND m.expires_at>? ORDER BY bm25(memory_fts),m.id,m.version LIMIT ?""",
            (
                expression,
                project_id,
                snapshot,
                _now_millis(),
                limit,
            ),
        ).fetchall()
        keys = (
            "id",
            "version",
            "projectId",
            "snapshot",
            "content",
            "contentSha256",
            "createdAt",
            "expiresAt",
            "provenance",
            "origin",
            "score",
        )
        hits = [dict(zip(keys, row)) for row in rows]
        for hit in hits:
            if hashlib.sha256(hit["content"].encode()).hexdigest() != hit["contentSha256"]:
                raise ValueError("Memory content integrity mismatch")
        return hits

    def invalidate(self, artifact_id: str, project_id: str) -> int:
        with self.db:
            cursor = self.db.execute(
                "UPDATE memories SET invalidated=1 WHERE id=? AND project_id=? AND invalidated=0",
                (artifact_id, project_id),
            )
            return cursor.rowcount

    def delete_project(self, project_id: str) -> int:
        with self.db:
            cursor = self.db.execute("DELETE FROM memories WHERE project_id=?", (project_id,))
            return cursor.rowcount

    def purge_expired(self, project_id: str) -> int:
        with self.db:
            cursor = self.db.execute(
                "DELETE FROM memories WHERE project_id=? AND expires_at<=?",
                (project_id, _now_millis()),
            )
            removed = cursor.rowcount
        try:
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.OperationalError:
            pass  # The deletion committed; checkpoint is best effort.
        return removed

    def close(self) -> None:
        self.db.close()
