"""Public CLI paths for explicit, project-scoped symbol retrieval."""

import json
import os
import subprocess
import sys

import pytest

from julius.cli import run
from julius.mcp_recovery import PROTOCOL_VERSION


def test_cli_symbol_index_search_refresh_and_invalidate(tmp_path, capsys) -> None:
    root = tmp_path / "project"
    root.mkdir()
    source = root / "module.py"
    source.write_text("def alpha():\n    return 1\n")
    common = ["--project", "p", "--project-root", str(root),
              "--snapshot", "snapshot-1", "--data-dir", str(tmp_path / "data")]

    assert run(["symbols", "index", "module.py", *common]) == 0
    indexed = json.loads(capsys.readouterr().out)
    assert indexed["symbols"] == 1
    assert indexed["changed"] is True

    assert run(["symbols", "search", "alpha", *common]) == 0
    hits = json.loads(capsys.readouterr().out)
    assert [hit["name"] for hit in hits] == ["alpha"]
    assert hits[0]["path"] == "module.py"

    source.write_text("def beta():\n    return 2\n")
    assert run(["symbols", "index", "module.py", *common]) == 0
    assert json.loads(capsys.readouterr().out)["changed"] is True
    assert run(["symbols", "search", "alpha", *common]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert run(["symbols", "search", "beta", *common]) == 0
    assert [hit["name"] for hit in json.loads(capsys.readouterr().out)] == ["beta"]

    assert run(["symbols", "invalidate", "module.py", *common]) == 0
    assert json.loads(capsys.readouterr().out) == {"removed": 1}
    assert run(["symbols", "search", "beta", *common]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_cli_symbol_project_root_binding_is_enforced(tmp_path, capsys) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "module.py").write_text("def one():\n    pass\n")
    common = ["--project", "p", "--snapshot", "snapshot-1",
              "--data-dir", str(tmp_path / "data")]
    assert run(["symbols", "index", "module.py", "--project-root", str(first), *common]) == 0
    capsys.readouterr()
    with pytest.raises(ValueError, match="bound to another root"):
        run(["symbols", "search", "one", "--project-root", str(second), *common])


def test_cli_mcp_symbol_search_requires_explicit_project_root(tmp_path, capsys) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "module.py").write_text("def alpha():\n    pass\n")
    data = tmp_path / "data"
    assert run(["symbols", "index", "module.py", "--project", "p",
                "--project-root", str(root), "--snapshot", "revision",
                "--data-dir", str(data)]) == 0
    capsys.readouterr()
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "fixture", "version": "1"},
        }},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "search_symbols", "arguments": {"query": "alpha", "snapshot": "revision"},
        }},
    ]
    input_text = "\n".join(json.dumps(message) for message in messages) + "\n"

    def invoke(*extra: str) -> list[dict]:
        process = subprocess.run(
            [sys.executable, "-m", "julius", "mcp", "recovery", "--project", "p",
             "--data-dir", str(data), *extra],
            input=input_text, text=True, capture_output=True, check=True,
            env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        )
        return [json.loads(line) for line in process.stdout.splitlines()]

    absent = invoke()
    assert [tool["name"] for tool in absent[1]["result"]["tools"]] == ["restore_artifact"]
    assert absent[2]["error"]["message"] == "Unknown tool"
    enabled = invoke("--project-root", str(root))
    assert [tool["name"] for tool in enabled[1]["result"]["tools"]] == [
        "restore_artifact", "search_symbols",
    ]
    result = json.loads(enabled[2]["result"]["content"][0]["text"])
    assert [hit["name"] for hit in result["hits"]] == ["alpha"]
