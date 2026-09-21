"""Offline, project-authorized symbol retrieval."""

from pathlib import Path

import pytest

from julius.memory import MemoryStore
from julius import symbols as symbol_module
from julius.symbols import MAX_FILE_BYTES, SymbolStore


def _store(tmp_path: Path, project: str = "alpha") -> tuple[MemoryStore, SymbolStore]:
    memory = MemoryStore(tmp_path / "memory.db")
    symbols = SymbolStore(memory, project_id=project, project_root=tmp_path / "repo")
    return memory, symbols


def test_snapshot_project_scope_and_content_hash_replacement(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "module.py"
    source.write_text("class Engine:\n    def run(self):\n        pass\n")
    memory, symbols = _store(tmp_path)
    try:
        first = symbols.index_file("module.py", snapshot="rev-a")
        assert first["changed"] is True
        assert first["symbols"] == 2
        assert symbols.index_file("module.py", snapshot="rev-a")["changed"] is False
        hits = symbols.search("run", snapshot="rev-a")
        assert len(hits) == 1
        assert hits[0]["qualifiedName"] == "Engine.run"
        assert hits[0]["contentSha256"] == first["contentSha256"]
        assert symbols.search("run", snapshot="rev-b") == []
        source.write_text("def build():\n    return 1\n")
        changed = symbols.index_file("module.py", snapshot="rev-a")
        assert changed["changed"] is True
        assert changed["contentSha256"] != first["contentSha256"]
        assert symbols.search("run", snapshot="rev-a") == []
        assert symbols.search("build", snapshot="rev-a")[0]["line"] == 1
        assert symbols.search("module", snapshot="rev-a")[0]["name"] == "build"
        assert symbols.search('" OR *', snapshot="rev-a") == []
        assert symbols.invalidate_file("module.py", snapshot="rev-a") == 1
        assert symbols.search("build", snapshot="rev-a") == []
    finally:
        symbols.close()
        memory.close()


def test_project_root_binding_and_delete_project(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.py").write_text("def common():\n    pass\n")
    memory, alpha = _store(tmp_path)
    beta = SymbolStore(memory, project_id="beta", project_root=root)
    try:
        alpha.index_file("main.py", snapshot="rev")
        beta.index_file("main.py", snapshot="rev")
        assert len(alpha.search("common", snapshot="rev")) == 1
        assert len(beta.search("common", snapshot="rev")) == 1
        other = tmp_path / "other"
        other.mkdir()
        with pytest.raises(ValueError, match="another root"):
            SymbolStore(memory, project_id="alpha", project_root=other)
        assert memory.delete_project("alpha") == 0
        with pytest.raises(ValueError, match="authorization has changed"):
            alpha.search("common", snapshot="rev")
        assert len(beta.search("common", snapshot="rev")) == 1
    finally:
        alpha.close()
        beta.close()
        memory.close()


def test_traversal_symlinks_and_oversized_sources_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "secret.py"
    outside.write_text("def secret():\n    pass\n")
    (root / "link.py").symlink_to(outside)
    (root / "linked_dir").symlink_to(tmp_path)
    (root / "large.py").write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    memory, symbols = _store(tmp_path)
    try:
        for name in ("../secret.py", "/secret.py", "nested/../secret.py", "a\\b.py"):
            with pytest.raises(ValueError, match="relative path"):
                symbols.index_file(name, snapshot="rev")
        for name in ("link.py", "linked_dir/secret.py"):
            with pytest.raises(OSError):
                symbols.index_file(name, snapshot="rev")
        with pytest.raises(ValueError, match="too large|bounded"):
            symbols.index_file("large.py", snapshot="rev")
        assert symbols.search("secret", snapshot="rev") == []
    finally:
        symbols.close()
        memory.close()
    root_link = tmp_path / "root_link"
    root_link.symlink_to(root)
    memory = MemoryStore(":memory:")
    try:
        with pytest.raises(ValueError, match="project root"):
            SymbolStore(memory, project_id="alpha", project_root=root_link)
    finally:
        memory.close()


def test_rust_and_typescript_declarations_and_limits(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "core.rs").write_text("pub struct Ledger {}\npub fn reconcile() {}\n")
    (root / "view.tsx").write_text("export function Dashboard() {}\nexport const panel = 1\n")
    memory, symbols = _store(tmp_path)
    try:
        symbols.index_file("core.rs", snapshot="rev")
        symbols.index_file("view.tsx", snapshot="rev")
        assert symbols.search("reconcile", snapshot="rev")[0]["kind"] == "fn"
        assert symbols.search("Dashboard", snapshot="rev")[0]["path"] == "view.tsx"
        with pytest.raises(ValueError, match="query or limit"):
            symbols.search("Ledger", snapshot="rev", limit=101)
        with pytest.raises(ValueError, match="snapshot"):
            symbols.search("Ledger", snapshot="")
    finally:
        symbols.close()
        memory.close()


def test_failed_refresh_invalidates_previous_index_and_file_cap(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "good.py"
    source.write_text("def stable():\n    pass\n")
    (root / "other.py").write_text("def other():\n    pass\n")
    memory, symbols = _store(tmp_path)
    try:
        symbols.index_file("good.py", snapshot="rev")
        source.write_text("def broken(\n")
        with pytest.raises(SyntaxError):
            symbols.index_file("good.py", snapshot="rev")
        assert symbols.search("stable", snapshot="rev") == []
        source.write_text("def stable():\n    pass\n")
        symbols.index_file("good.py", snapshot="rev")
        monkeypatch.setattr(symbol_module, "MAX_FILES_PER_SNAPSHOT", 1)
        with pytest.raises(ValueError, match="Too many indexed files"):
            symbols.index_file("other.py", snapshot="rev")
    finally:
        symbols.close()
        memory.close()
