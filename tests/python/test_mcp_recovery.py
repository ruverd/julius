import hashlib
from io import BytesIO
import json
from pathlib import Path
import time

import pytest

from julius.artifacts import ArtifactStore
from julius.memory import MemoryStore
import julius.mcp_recovery as mcp_recovery
from julius.mcp_recovery import MAX_MESSAGE_BYTES, PROTOCOL_VERSION, serve_stdio
from julius.symbols import SymbolStore


def exchange(
    store: ArtifactStore, project: str, messages: list[dict],
    *, symbol_memory: MemoryStore | None = None, project_root: Path | None = None,
    memory_store: MemoryStore | None = None,
) -> list[dict]:
    source = BytesIO(b"".join((json.dumps(message) + "\n").encode() for message in messages))
    sink = BytesIO()
    serve_stdio(
        store, project, source, sink, symbol_memory=symbol_memory, project_root=project_root,
        memory_store=memory_store,
    )
    return [json.loads(line) for line in sink.getvalue().splitlines()]


def session(*messages: dict) -> list[dict]:
    return [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        *messages,
    ]


def call(artifact_id: str, request_id: int = 3) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {
        "name": "restore_artifact", "arguments": {"artifactId": artifact_id}}}


def symbol_call(arguments: dict, request_id: int = 3) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {
        "name": "search_symbols", "arguments": arguments}}


def memory_call(arguments: dict, request_id: int = 3) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {
        "name": "search_memory", "arguments": arguments}}


def test_memory_tool_is_opt_in_scoped_and_preserves_evidence(tmp_path: Path):
    from test_memory import memory as make_memory

    memory_store = MemoryStore(tmp_path / "memory.db")
    try:
        memory_store.put(make_memory(projectId="project", provenance="inferred"))
        memory_store.put(make_memory(projectId="other", id="secret", content="Secret compiler"))
        artifacts = ArtifactStore(tmp_path / "artifacts")
        disabled = exchange(artifacts, "project", session(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            memory_call({"query": "compiler", "snapshot": "commit-a"}),
        ))
        assert [tool["name"] for tool in disabled[1]["result"]["tools"]] == ["restore_artifact"]
        assert disabled[2]["error"]["code"] == -32602
        replies = exchange(artifacts, "project", session(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            memory_call({"query": "compiler", "snapshot": "commit-a"}),
            memory_call({"query": "compiler", "snapshot": "wrong"}, 4),
            memory_call({"query": "compiler", "snapshot": "commit-a", "projectId": "other"}, 5),
            memory_call({"query": "compiler", "snapshot": "commit-a", "limit": True}, 6),
            memory_call({"query": "compiler", "snapshot": "commit-a", "limit": 101}, 7),
            memory_call({"query": "compiler"}, 8),
        ), memory_store=memory_store)
        assert [tool["name"] for tool in replies[1]["result"]["tools"]] == [
            "restore_artifact", "search_memory",
        ]
        hit = json.loads(replies[2]["result"]["content"][0]["text"])["hits"][0]
        assert hit["projectId"] == "project"
        assert hit["provenance"] == "inferred"
        assert hit["origin"] == "log:17"
        assert hit["expiresAt"] and hit["contentSha256"]
        assert json.loads(replies[3]["result"]["content"][0]["text"])["hits"] == []
        assert all(reply["error"]["code"] == -32602 for reply in replies[4:])
        assert "Secret compiler" not in json.dumps(replies)
    finally:
        memory_store.close()


def test_handshake_list_and_restore(tmp_path: Path):
    store = ArtifactStore(tmp_path)
    item = store.put("project", "private original")
    replies = exchange(store, "project", session(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, call(item["id"])))
    assert replies[0]["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert replies[0]["result"]["capabilities"] == {"tools": {}}
    assert [tool["name"] for tool in replies[1]["result"]["tools"]] == ["restore_artifact"]
    assert replies[2]["result"]["content"] == [{"type": "text", "text": "private original"}]


def test_project_boundary_invalid_id_and_expiry(tmp_path: Path):
    store = ArtifactStore(tmp_path)
    other = store.put("other", "secret")
    short = store.put("project", "expired", ttl_ms=1)
    time.sleep(0.005)
    replies = exchange(store, "project", session(call(other["id"]), call("../escape", 4), call(short["id"], 5)))
    assert all(reply["result"]["isError"] for reply in replies[1:])
    assert "secret" not in json.dumps(replies)


def test_symlink_rejected_and_protocol_errors(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")
    item = store.put("project", "secret")
    directory = store.root / hashlib.sha256(b"project").hexdigest()
    body = directory / f"{item['id']}.txt"
    body.unlink()
    body.symlink_to(tmp_path / "outside")
    replies = exchange(store, "project", session(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "wrong"}},
        call(item["id"])))
    assert replies[1]["error"]["code"] == -32602
    assert replies[2]["result"]["isError"] is True


def test_bounded_messages_and_preinitialization(tmp_path: Path):
    store = ArtifactStore(tmp_path)
    replies = exchange(store, "project", [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])
    assert replies[0]["error"]["code"] == -32600
    sink = BytesIO()
    serve_stdio(store, "project", BytesIO(b"x" * (MAX_MESSAGE_BYTES + 2) + b"\n"), sink)
    assert sink.getvalue() == b""


def test_oversized_restore_returns_complete_error_without_original(tmp_path: Path, monkeypatch):
    store = ArtifactStore(tmp_path)
    original = "secret marker " + "é" * 200
    item = store.put("project", original)
    monkeypatch.setattr(mcp_recovery, "MAX_RESPONSE_BYTES", 200)
    sink = BytesIO()
    source = BytesIO(b"".join(
        (json.dumps(message) + "\n").encode() for message in session(call(item["id"]))
    ))
    serve_stdio(store, "project", source, sink)
    lines = sink.getvalue().splitlines(keepends=True)
    assert all(len(line) <= 200 for line in lines)
    replies = [json.loads(line) for line in lines]
    assert replies[1]["error"] == {"code": -32000, "message": "Response exceeds size limit"}
    assert original.encode() not in sink.getvalue()
    assert store.get("project", item["id"]) == original


def test_oversized_search_fails_closed_and_keeps_project_scope(tmp_path: Path, monkeypatch):
    class LargeMemory:
        def search(self, project_id, query, *, snapshot, limit):
            assert project_id == "project"
            return [{"content": "secret marker " + "x" * 500}]

    monkeypatch.setattr(mcp_recovery, "MAX_RESPONSE_BYTES", 200)
    replies = exchange(ArtifactStore(tmp_path), "project", session(
        memory_call({"query": "secret", "snapshot": "rev"}),
        memory_call({"query": "secret", "snapshot": "rev", "projectId": "other"}, 4),
    ), memory_store=LargeMemory())
    assert replies[1]["error"] == {"code": -32000, "message": "Response exceeds size limit"}
    assert replies[2]["error"]["code"] == -32602
    assert "secret marker" not in json.dumps(replies)


def test_symbol_tool_requires_explicit_project_root_and_snapshot(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "module.py").write_text("def compile_graph():\n    pass\n")
    memory = MemoryStore(tmp_path / "memory.db")
    index = SymbolStore(memory, project_id="project", project_root=root)
    try:
        index.index_file("module.py", snapshot="rev-a")
    finally:
        index.close()
    artifacts = ArtifactStore(tmp_path / "artifacts")
    no_root = exchange(artifacts, "project", session(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        symbol_call({"query": "compile", "snapshot": "rev-a"}),
    ))
    assert [tool["name"] for tool in no_root[1]["result"]["tools"]] == ["restore_artifact"]
    assert no_root[2]["error"]["code"] == -32602
    replies = exchange(artifacts, "project", session(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        symbol_call({"query": "compile_graph", "snapshot": "rev-a"}),
        symbol_call({"query": "compile_graph", "snapshot": "rev-b"}, 4),
        symbol_call({"query": "compile_graph"}, 5),
        symbol_call({"query": "compile_graph", "snapshot": "rev-a", "projectId": "other"}, 6),
    ), symbol_memory=memory, project_root=root)
    assert [tool["name"] for tool in replies[1]["result"]["tools"]] == [
        "restore_artifact", "search_symbols",
    ]
    found = json.loads(replies[2]["result"]["content"][0]["text"])
    assert found["snapshot"] == "rev-a"
    assert [(hit["name"], hit["path"]) for hit in found["hits"]] == [
        ("compile_graph", "module.py"),
    ]
    assert json.loads(replies[3]["result"]["content"][0]["text"])["hits"] == []
    assert replies[4]["error"]["code"] == -32602
    assert replies[5]["error"]["code"] == -32602
    memory.close()


def test_symbol_tool_cannot_change_project_and_rejects_unsafe_root(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "private.py").write_text("def private_symbol():\n    pass\n")
    memory = MemoryStore(tmp_path / "memory.db")
    index = SymbolStore(memory, project_id="other", project_root=root)
    try:
        index.index_file("private.py", snapshot="rev")
    finally:
        index.close()
    artifacts = ArtifactStore(tmp_path / "artifacts")
    replies = exchange(artifacts, "project", session(
        symbol_call({"query": "private_symbol", "snapshot": "rev"}),
        symbol_call({"query": "private_symbol", "snapshot": "rev", "limit": True}, 4),
        symbol_call({"query": "private_symbol", "snapshot": "rev", "limit": 101}, 5),
    ), symbol_memory=memory, project_root=root)
    assert json.loads(replies[1]["result"]["content"][0]["text"])["hits"] == []
    assert replies[2]["error"]["code"] == -32602
    assert replies[3]["error"]["code"] == -32602
    unsafe = tmp_path / "unsafe"
    unsafe.symlink_to(root)
    with pytest.raises(ValueError, match="project root"):
        exchange(artifacts, "project", session(), symbol_memory=memory, project_root=unsafe)
    with pytest.raises(ValueError, match="together"):
        exchange(artifacts, "project", session(), symbol_memory=memory)
    memory.close()
