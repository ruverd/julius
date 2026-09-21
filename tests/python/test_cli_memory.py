"""Explicit lexical-memory CLI and opt-in MCP exposure."""

import json
import os
from pathlib import Path
import subprocess
import sys

from test_memory import memory


def _run(data_dir: Path, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "julius", *args, "--data-dir", str(data_dir)],
        input=input_text, text=True, capture_output=True, timeout=10,
        env={**os.environ, "JULIUS_HOME": str(data_dir)},
    )


def test_memory_cli_put_search_invalidate_and_project_boundary(tmp_path: Path):
    data_dir = tmp_path / "data"
    record = tmp_path / "record.json"
    record.write_text(json.dumps(memory()))
    mismatch = _run(data_dir, "memory", "put", str(record), "--project", "other")
    assert mismatch.returncode == 1
    assert json.loads(_run(
        data_dir, "memory", "search", "compiler", "--project", "other", "--snapshot", "commit-a",
    ).stdout) == []
    stored = _run(data_dir, "memory", "put", str(record), "--project", "one")
    assert stored.returncode == 0, stored.stderr
    assert json.loads(stored.stdout) == {"stored": True, "id": "fact", "version": 1}
    found = _run(data_dir, "memory", "search", "compiler", "--project", "one", "--snapshot", "commit-a")
    assert found.returncode == 0, found.stderr
    assert json.loads(found.stdout)[0]["origin"] == "log:17"
    wrong_snapshot = _run(
        data_dir, "memory", "search", "compiler", "--project", "one", "--snapshot", "other",
    )
    assert json.loads(wrong_snapshot.stdout) == []
    invalidated = _run(data_dir, "memory", "invalidate", "fact", "--project", "one")
    assert json.loads(invalidated.stdout) == {"invalidated": 1}
    assert json.loads(_run(
        data_dir, "memory", "search", "compiler", "--project", "one", "--snapshot", "commit-a",
    ).stdout) == []


def test_memory_cli_history_is_project_scoped_metadata_and_paged(tmp_path: Path):
    data_dir = tmp_path / "data"
    for project in ("one", "other"):
        item = memory(projectId=project)
        record = tmp_path / f"{project}.json"
        record.write_text(json.dumps(item))
        assert _run(data_dir, "memory", "put", str(record), "--project", project).returncode == 0
    invalidated = _run(
        data_dir, "memory", "invalidate", "fact", "--project", "one",
        "--invalidation-reason", "source_changed", "--source", "manual-review",
    )
    assert invalidated.returncode == 0, invalidated.stderr
    page = _run(data_dir, "memory", "history", "--project", "one", "--limit", "1")
    assert page.returncode == 0, page.stderr
    data = json.loads(page.stdout)
    assert data["limit"] == 1 and data["offset"] == 0 and data["nextOffset"] == 1
    assert len(data["records"]) == 1
    record = data["records"][0]
    assert record["projectId"] == "one"
    assert record["invalidated"] is True
    assert record["invalidationReason"] == "source_changed"
    assert record["invalidationSource"] == "manual-review"
    assert record["invalidatedAt"] is not None
    assert "content" not in record
    next_page = json.loads(_run(
        data_dir, "memory", "history", "--project", "one", "--limit", "1",
        "--offset", "1",
    ).stdout)
    assert next_page["records"] == [] and next_page["nextOffset"] is None
    assert _run(data_dir, "memory", "history", "--project", "one", "--limit", "0").returncode == 1


def test_mcp_memory_search_requires_explicit_flag(tmp_path: Path):
    data_dir = tmp_path / "data"
    record = tmp_path / "record.json"
    record.write_text(json.dumps(memory()))
    assert _run(data_dir, "memory", "put", str(record), "--project", "one").returncode == 0
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "search_memory", "arguments": {"query": "compiler", "snapshot": "commit-a"}}},
    ]
    payload = "".join(json.dumps(message) + "\n" for message in messages)
    default = _run(data_dir, "mcp", "recovery", "--project", "one", input_text=payload)
    assert default.returncode == 0, default.stderr
    default_replies = [json.loads(line) for line in default.stdout.splitlines()]
    assert [tool["name"] for tool in default_replies[1]["result"]["tools"]] == ["restore_artifact"]
    assert default_replies[2]["error"]["code"] == -32602
    enabled = _run(
        data_dir, "mcp", "recovery", "--project", "one", "--memory-search", input_text=payload,
    )
    assert enabled.returncode == 0, enabled.stderr
    replies = [json.loads(line) for line in enabled.stdout.splitlines()]
    assert [tool["name"] for tool in replies[1]["result"]["tools"]] == [
        "restore_artifact", "search_memory",
    ]
    hits = json.loads(replies[2]["result"]["content"][0]["text"])["hits"]
    assert len(hits) == 1 and hits[0]["projectId"] == "one"
