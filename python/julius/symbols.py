"""Bounded, offline code-symbol retrieval for an authorized project root."""

import ast
import hashlib
import os
from pathlib import Path
import re
import stat

from .memory import MemoryStore


MAX_FILE_BYTES = 256 * 1024
MAX_SYMBOLS_PER_FILE = 512
MAX_FILES_PER_SNAPSHOT = 2048
MAX_PATH_BYTES = 1024
SOURCE_SUFFIXES = frozenset({".py", ".rs", ".ts", ".tsx", ".js", ".jsx"})
_RUST_DECLARATION = re.compile(
    r'^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?'
    r'(?:extern\s+"[^"]+"\s+)?(fn|struct|enum|trait|mod|type|const|static)\s+'
    r'([A-Za-z_][A-Za-z_0-9]*)'
)
_JS_DECLARATION = re.compile(
    r'^\s*(?:export\s+)?(?:default\s+)?(?:declare\s+)?'
    r'(?:async\s+)?(function|class|interface|type|enum|const|let)\s+'
    r'([A-Za-z_$][A-Za-z_0-9$]*)'
)


def _identity(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 256:
        raise ValueError(f"Invalid {label}")
    return value


def _relative_path(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > MAX_PATH_BYTES:
        raise ValueError("Invalid relative path")
    if "\\" in value or "\x00" in value or value.startswith("/"):
        raise ValueError("Invalid relative path")
    parts = tuple(value.split("/"))
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("Invalid relative path")
    if Path(parts[-1]).suffix not in SOURCE_SUFFIXES:
        raise ValueError("Unsupported source file")
    return parts


def _read_source(root_fd: int, parts: tuple[str, ...]) -> bytes:
    """Open each component relative to a directory FD, rejecting symlinks."""
    flags = os.O_RDONLY | os.O_NOFOLLOW
    directory = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            next_directory = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        source = os.open(parts[-1], flags | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(source)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
                raise ValueError("Source is not a bounded regular file")
            chunks: list[bytes] = []
            remaining = MAX_FILE_BYTES + 1
            while remaining:
                chunk = os.read(source, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            if len(content) > MAX_FILE_BYTES:
                raise ValueError("Source file is too large")
            return content
        finally:
            os.close(source)
    finally:
        os.close(directory)


def _python_symbols(content: str) -> list[tuple[str, str, str, int, str]]:
    tree = ast.parse(content)
    lines = content.splitlines()
    result: list[tuple[str, str, str, int, str]] = []

    def visit(body: list[ast.stmt], scope: str = "") -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = node.name
                qualified = f"{scope}.{name}" if scope else name
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                signature = lines[node.lineno - 1].strip()[:300]
                result.append((name, qualified, kind, node.lineno, signature))
                if len(result) > MAX_SYMBOLS_PER_FILE:
                    raise ValueError("Too many source symbols")
                visit(node.body, qualified)

    visit(tree.body)
    return result


def _pattern_symbols(
    content: str, pattern: re.Pattern[str]
) -> list[tuple[str, str, str, int, str]]:
    result: list[tuple[str, str, str, int, str]] = []
    for line_number, line in enumerate(content.splitlines(), 1):
        match = pattern.match(line)
        if match is None:
            continue
        kind, name = match.groups()
        result.append((name, name, kind, line_number, line.strip()[:300]))
        if len(result) > MAX_SYMBOLS_PER_FILE:
            raise ValueError("Too many source symbols")
    return result


class SymbolStore:
    """Index explicit files under one root; searches require the exact snapshot."""

    def __init__(self, memory: MemoryStore, *, project_id: str, project_root: str | Path):
        self.db = memory.db
        self.project_id = _identity(project_id, "project ID")
        root = Path(project_root).absolute()
        if root.is_symlink() or not root.is_dir():
            raise ValueError("Invalid project root")
        self.root = root.resolve(strict=True)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS symbol_roots (
                project_id TEXT PRIMARY KEY, root TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS symbol_files (
                project_id TEXT NOT NULL, snapshot TEXT NOT NULL, path TEXT NOT NULL,
                content_sha256 TEXT NOT NULL, PRIMARY KEY(project_id,snapshot,path)
            );
            CREATE TABLE IF NOT EXISTS symbols (
                id INTEGER PRIMARY KEY, project_id TEXT NOT NULL, snapshot TEXT NOT NULL,
                path TEXT NOT NULL, content_sha256 TEXT NOT NULL, name TEXT NOT NULL,
                qualified_name TEXT NOT NULL, kind TEXT NOT NULL, line INTEGER NOT NULL,
                signature TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS symbols_scope ON symbols(project_id,snapshot,path);
            CREATE VIRTUAL TABLE IF NOT EXISTS symbol_fts USING fts5(
                name, qualified_name, signature, path, content='symbols', content_rowid='id'
            );
            CREATE TRIGGER IF NOT EXISTS symbol_ai AFTER INSERT ON symbols BEGIN
                INSERT INTO symbol_fts(rowid,name,qualified_name,signature,path)
                VALUES(new.id,new.name,new.qualified_name,new.signature,new.path);
            END;
            CREATE TRIGGER IF NOT EXISTS symbol_ad AFTER DELETE ON symbols BEGIN
                INSERT INTO symbol_fts(symbol_fts,rowid,name,qualified_name,signature,path)
                VALUES('delete',old.id,old.name,old.qualified_name,old.signature,old.path);
            END;
        """)
        root_string = str(self.root)
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO symbol_roots(project_id,root) VALUES(?,?)",
                (self.project_id, root_string),
            )
            stored = self.db.execute(
                "SELECT root FROM symbol_roots WHERE project_id=?", (self.project_id,)
            ).fetchone()
            if stored is None or stored[0] != root_string:
                raise ValueError("Project ID is bound to another root")
        self._root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def _check_root_binding(self) -> None:
        stored = self.db.execute(
            "SELECT root FROM symbol_roots WHERE project_id=?", (self.project_id,)
        ).fetchone()
        if stored is None or stored[0] != str(self.root):
            raise ValueError("Project root authorization has changed")

    def index_file(self, path: str, *, snapshot: str) -> dict[str, object]:
        """Replace this file's symbols when its bytes differ within this snapshot."""
        _identity(snapshot, "snapshot")
        parts = _relative_path(path)
        self._check_root_binding()
        try:
            content_bytes = _read_source(self._root_fd, parts)
            content = content_bytes.decode("utf-8")
        except (OSError, ValueError, UnicodeDecodeError):
            self.invalidate_file(path, snapshot=snapshot)
            raise
        digest = hashlib.sha256(content_bytes).hexdigest()
        old = self.db.execute(
            "SELECT content_sha256 FROM symbol_files WHERE project_id=? AND snapshot=? AND path=?",
            (self.project_id, snapshot, path),
        ).fetchone()
        if old is not None and old[0] == digest:
            count = self.db.execute(
                "SELECT count(*) FROM symbols WHERE project_id=? AND snapshot=? AND path=?",
                (self.project_id, snapshot, path),
            ).fetchone()
            return {"path": path, "contentSha256": digest, "symbols": count[0], "changed": False}
        if old is None:
            count = self.db.execute(
                "SELECT count(*) FROM symbol_files WHERE project_id=? AND snapshot=?",
                (self.project_id, snapshot),
            ).fetchone()
            if count is not None and count[0] >= MAX_FILES_PER_SNAPSHOT:
                raise ValueError("Too many indexed files in snapshot")
        try:
            if parts[-1].endswith(".py"):
                parsed = _python_symbols(content)
            elif parts[-1].endswith(".rs"):
                parsed = _pattern_symbols(content, _RUST_DECLARATION)
            else:
                parsed = _pattern_symbols(content, _JS_DECLARATION)
        except (SyntaxError, ValueError):
            self.invalidate_file(path, snapshot=snapshot)
            raise
        with self.db:
            self.db.execute(
                "DELETE FROM symbols WHERE project_id=? AND snapshot=? AND path=?",
                (self.project_id, snapshot, path),
            )
            self.db.execute(
                "INSERT INTO symbol_files(project_id,snapshot,path,content_sha256) "
                "VALUES(?,?,?,?) ON CONFLICT(project_id,snapshot,path) "
                "DO UPDATE SET content_sha256=excluded.content_sha256",
                (self.project_id, snapshot, path, digest),
            )
            self.db.executemany(
                "INSERT INTO symbols(project_id,snapshot,path,content_sha256,name,"
                "qualified_name,kind,line,signature) VALUES(?,?,?,?,?,?,?,?,?)",
                [(self.project_id, snapshot, path, digest, *symbol) for symbol in parsed],
            )
        return {"path": path, "contentSha256": digest, "symbols": len(parsed), "changed": True}

    def invalidate_file(self, path: str, *, snapshot: str) -> int:
        """Remove a deleted or superseded file from one snapshot."""
        _identity(snapshot, "snapshot")
        _relative_path(path)
        self._check_root_binding()
        with self.db:
            removed = self.db.execute(
                "DELETE FROM symbols WHERE project_id=? AND snapshot=? AND path=?",
                (self.project_id, snapshot, path),
            ).rowcount
            self.db.execute(
                "DELETE FROM symbol_files WHERE project_id=? AND snapshot=? AND path=?",
                (self.project_id, snapshot, path),
            )
        return removed

    def search(self, query: str, *, snapshot: str, limit: int = 20) -> list[dict[str, object]]:
        _identity(snapshot, "snapshot")
        self._check_root_binding()
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
            """SELECT s.path,s.name,s.qualified_name,s.kind,s.line,s.signature,
                s.content_sha256,bm25(symbol_fts)
                FROM symbol_fts JOIN symbols s ON s.id=symbol_fts.rowid
                WHERE symbol_fts MATCH ? AND s.project_id=? AND s.snapshot=?
                ORDER BY bm25(symbol_fts),s.path,s.line LIMIT ?""",
            (expression, self.project_id, snapshot, limit),
        ).fetchall()
        keys = (
            "path", "name", "qualifiedName", "kind", "line", "signature", "contentSha256", "score"
        )
        return [dict(zip(keys, row)) for row in rows]

    def close(self) -> None:
        os.close(self._root_fd)
