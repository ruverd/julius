import hashlib
from io import BytesIO
import json
from pathlib import Path
import time

from julius.artifacts import ArtifactStore
from julius.mcp_recovery import MAX_MESSAGE_BYTES, PROTOCOL_VERSION, serve_stdio


def exchange(store: ArtifactStore, project: str, messages: list[dict]) -> list[dict]:
    source = BytesIO(b"".join((json.dumps(message) + "\n").encode() for message in messages))
    sink = BytesIO()
    serve_stdio(store, project, source, sink)
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
