import json
import os
import subprocess
import sys

from julius.mcp_recovery import PROTOCOL_VERSION
from julius.sdk import Julius


def _command(tmp_path, *arguments, input_text):
    return subprocess.run(
        [sys.executable, "-m", "julius", *arguments, "--data-dir", str(tmp_path)],
        input=input_text,
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        check=True,
    ).stdout


def test_hook_cli_requires_recovery_and_mcp_restores_original(tmp_path):
    line = "ordinary neutral line with enough characters for deterministic reduction and more detail"
    original = "\n".join([line] * 6)
    event = {
        "hook_event_name": "PostToolUse",
        "session_id": "session-1",
        "tool_use_id": "tool-1",
        "tool_name": "Bash",
        "tool_input": {"command": "printf fixture"},
        "tool_response": {
            "stdout": original,
            "stderr": "",
            "interrupted": False,
            "isImage": False,
        },
    }
    arguments = ("hook", "claude-post-tool-use", "--project", "project", "--profile", "safe")
    assert _command(tmp_path, *arguments, input_text=json.dumps(event)) == ""
    assert list(tmp_path.rglob("*.txt")) == []
    output = json.loads(_command(
        tmp_path, *arguments, "--recovery-available", input_text=json.dumps(event)
    ))
    replacement = output["hookSpecificOutput"]["updatedToolOutput"]["stdout"]
    assert len(replacement) < len(original)
    artifact_id = next(tmp_path.rglob("*.txt")).stem
    assert artifact_id in replacement
    with Julius(tmp_path) as julius:
        recorded = julius.ledger.events()
    assert len(recorded) == 1
    assert recorded[0]["eventType"] == "transform"
    assert recorded[0]["payload"]["sent"] is False
    assert recorded[0]["payload"]["inputArtifactId"] == artifact_id
    assert recorded[0]["evidence"] == "heuristic_estimate"

    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "fixture", "version": "1"},
        }},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "restore_artifact", "arguments": {"artifactId": artifact_id},
        }},
    ]
    replies = [json.loads(line) for line in _command(
        tmp_path, "mcp", "recovery", "--project", "project",
        input_text="\n".join(json.dumps(message) for message in messages) + "\n",
    ).splitlines()]
    assert replies[1]["result"]["content"][0]["text"] == original


def test_hook_cli_fails_open_for_invalid_or_oversized_input(tmp_path):
    args = ("hook", "claude-post-tool-use", "--project", "project", "--profile", "safe", "--recovery-available")
    assert _command(tmp_path, *args, input_text="not json") == ""
    assert _command(tmp_path, *args, input_text="x" * 65537) == ""
    assert list(tmp_path.rglob("*.txt")) == []
