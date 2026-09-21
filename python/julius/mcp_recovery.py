"""Small offline MCP stdio server for project-scoped artifact recovery."""

import json
from pathlib import Path
import sys
from typing import Any, BinaryIO

from .artifacts import ArtifactStore

PROTOCOL_VERSION = "2025-06-18"
MAX_MESSAGE_BYTES = 64 * 1024
TOOL_NAME = "restore_artifact"
TOOL = {
    "name": TOOL_NAME,
    "description": "Restore a stored original for this server's fixed project before it expires.",
    "inputSchema": {
        "type": "object",
        "properties": {"artifactId": {"type": "string", "description": "Julius artifact UUID"}},
        "required": ["artifactId"],
        "additionalProperties": False,
    },
}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


class RecoveryServer:
    """A single-session MCP server; project authorization is fixed at construction."""

    def __init__(self, store: ArtifactStore, project_id: str):
        if not isinstance(project_id, str) or not project_id or len(project_id) > 256:
            raise ValueError("Invalid project ID")
        self.store = store
        self.project_id = project_id
        self.initialized = False
        self.ready = False

    def handle(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, -32600, "Invalid Request")
        request_id = message.get("id")
        has_id = "id" in message
        if has_id and (isinstance(request_id, bool) or not isinstance(request_id, (str, int))):
            return _error(None, -32600, "Invalid Request")
        method = message.get("method")
        if not isinstance(method, str):
            return _error(request_id if has_id else None, -32600, "Invalid Request")
        if not has_id:
            if method == "notifications/initialized" and self.initialized:
                self.ready = True
            return None
        params = message.get("params", {})
        if not isinstance(params, dict):
            return _error(request_id, -32602, "Invalid params")
        if method == "initialize":
            if self.initialized:
                return _error(request_id, -32600, "Already initialized")
            if not isinstance(params.get("protocolVersion"), str):
                return _error(request_id, -32602, "Missing protocol version")
            if not isinstance(params.get("capabilities"), dict) or not isinstance(
                params.get("clientInfo"), dict
            ):
                return _error(request_id, -32602, "Invalid initialization params")
            self.initialized = True
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "julius-recovery", "version": "0.2.0"},
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if not self.ready:
            return _error(request_id, -32600, "Session not initialized")
        if method == "tools/list":
            if params.get("cursor") is not None:
                return _error(request_id, -32602, "Invalid cursor")
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": [TOOL]}}
        if method == "tools/call":
            if params.get("name") != TOOL_NAME:
                return _error(request_id, -32602, "Unknown tool")
            arguments = params.get("arguments", {})
            if not isinstance(arguments, dict) or set(arguments) != {"artifactId"} or not isinstance(
                arguments.get("artifactId"), str
            ):
                return _error(request_id, -32602, "Invalid tool arguments")
            try:
                original = self.store.get(self.project_id, arguments["artifactId"])
            except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": "Artifact unavailable or invalid"}],
                        "isError": True,
                    },
                }
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"content": [{"type": "text", "text": original}], "isError": False},
            }
        return _error(request_id, -32601, "Method not found")


def serve_stdio(
    store: ArtifactStore, project_id: str, input_stream: BinaryIO | None = None, output_stream: BinaryIO | None = None
) -> None:
    """Read one JSON-RPC object per UTF-8 line; stdout contains protocol messages only."""
    source = input_stream if input_stream is not None else sys.stdin.buffer
    sink = output_stream if output_stream is not None else sys.stdout.buffer
    server = RecoveryServer(store, project_id)
    while True:
        line = source.readline(MAX_MESSAGE_BYTES + 2)
        if not line:
            return
        if len(line) > MAX_MESSAGE_BYTES + 1 or not line.endswith(b"\n"):
            # A truncated line cannot be framed safely; terminate the session.
            return
        response: dict[str, Any] | None
        try:
            message = json.loads(line)
        except (UnicodeError, json.JSONDecodeError):
            response = _error(None, -32700, "Parse error")
        else:
            response = server.handle(message)
        if response is not None:
            sink.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
            sink.flush()


def main() -> None:
    """Entry point for `python -m julius.mcp_recovery ROOT PROJECT_ID`."""
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m julius.mcp_recovery ARTIFACT_ROOT PROJECT_ID")
    serve_stdio(ArtifactStore(Path(sys.argv[1])), sys.argv[2])


if __name__ == "__main__":
    main()
