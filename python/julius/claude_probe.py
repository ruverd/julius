"""Bounded, offline subprocess probe for Julius's Claude hook and MCP protocol."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .mcp_recovery import PROTOCOL_VERSION, TOOL_NAME


def probe_local_protocol(
    *, python_executable: str = sys.executable, timeout_seconds: float = 5.0
) -> dict[str, Any]:
    """Test only local Julius processes; never start Claude or access client config."""
    if timeout_seconds <= 0:
        raise ValueError("Timeout must be positive")
    evidence: dict[str, bool] = {
        "hook_candidate": False,
        "mcp_initialize": False,
        "mcp_tools_list": False,
        "artifact_restore": False,
    }
    result: dict[str, Any] = {
        "scope": "local_protocol", "available": False, "evidence": evidence,
        "error": None,
    }
    line = "ordinary neutral line with enough characters for deterministic reduction and more detail"
    original = "\n".join([line] * 6)
    event = {
        "hook_event_name": "PostToolUse", "tool_name": "Bash",
        "tool_input": {"command": "printf fixture"},
        "tool_response": {"stdout": original, "stderr": "", "interrupted": False, "isImage": False},
    }
    env = os.environ.copy()
    source_root = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (source_root, env.get("PYTHONPATH"))))
    try:
        with tempfile.TemporaryDirectory(prefix="julius-claude-probe-") as directory:
            base = [python_executable, "-m", "julius"]
            scope = ["--project", "julius-local-probe", "--data-dir", directory]
            hook = subprocess.run(
                [*base, "hook", "claude-post-tool-use", *scope,
                 "--profile", "safe", "--recovery-available"],
                input=json.dumps(event), text=True, capture_output=True,
                timeout=timeout_seconds, env=env, check=False,
            )
            if hook.returncode != 0:
                raise ValueError("Hook process failed")
            payload = json.loads(hook.stdout)
            candidate = payload["hookSpecificOutput"]["updatedToolOutput"]["stdout"]
            artifacts = list((Path(directory) / "artifacts").rglob("*.txt"))
            if not isinstance(candidate, str) or len(candidate) >= len(original) or len(artifacts) != 1:
                raise ValueError("Hook did not produce one shorter recoverable candidate")
            artifact_id = artifacts[0].stem
            if artifact_id not in candidate:
                raise ValueError("Candidate does not reference its artifact")
            evidence["hook_candidate"] = True
            messages = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                    "clientInfo": {"name": "julius-local-probe", "version": "1"},
                }},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                    "name": TOOL_NAME, "arguments": {"artifactId": artifact_id},
                }},
            ]
            mcp = subprocess.run(
                [*base, "mcp", "recovery", *scope],
                input="\n".join(json.dumps(item) for item in messages) + "\n",
                text=True, capture_output=True, timeout=timeout_seconds, env=env, check=False,
            )
            if mcp.returncode != 0:
                raise ValueError("MCP process failed")
            replies = {reply["id"]: reply for reply in map(json.loads, mcp.stdout.splitlines())}
            evidence["mcp_initialize"] = (
                replies[1]["result"]["protocolVersion"] == PROTOCOL_VERSION
                and "tools" in replies[1]["result"]["capabilities"]
            )
            evidence["mcp_tools_list"] = any(
                tool.get("name") == TOOL_NAME for tool in replies[2]["result"]["tools"]
            )
            evidence["artifact_restore"] = (
                replies[3]["result"].get("isError") is False
                and replies[3]["result"]["content"][0]["text"] == original
            )
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError, IndexError) as exc:
        result["error"] = type(exc).__name__
    result["available"] = all(evidence.values())
    return result
