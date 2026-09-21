import hashlib
from io import BytesIO
import json
from pathlib import Path
import time

import pytest

from julius.artifacts import ArtifactStore
from julius.memory import MemoryStore
from julius.mcp_recovery import MAX_MESSAGE_BYTES, PROTOCOL_VERSION, serve_stdio
from julius.symbols import SymbolStore


def exchange(
    store: ArtifactStore, project: str, messages: list[dict],
    *, symbol_memory: MemoryStore | None = None, project_root: Path | None = None,
) -> list[dict]:
    source = BytesIO(b"".join((json.dumps(message) + "\n").encode() for message in messages))
    sink = BytesIO()
    serve_stdio(
        store, project, source, sink, symbol_memory=symbol_memory, project_root=project_root,
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
