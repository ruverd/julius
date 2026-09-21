"""Small offline MCP stdio server for project-scoped recovery and symbol search."""

import json
from pathlib import Path
import sqlite3
import sys
from typing import Any, BinaryIO

from .artifacts import ArtifactStore
from .memory import MemoryStore
from .symbols import SymbolStore

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
SYMBOL_TOOL_NAME = "search_symbols"
SYMBOL_TOOL = {
    "name": SYMBOL_TOOL_NAME,
    "description": "Search indexed code symbols for this server's fixed project and exact snapshot.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Literal lexical search terms"},
            "snapshot": {"type": "string", "description": "Exact indexed project revision"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        },
        "required": ["query", "snapshot"],
        "additionalProperties": False,
    },
}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


class RecoveryServer:
    """A single-session MCP server; project authorization is fixed at construction."""

    def __init__(
        self,
        store: ArtifactStore,
        project_id: str,
        *,
        symbol_memory: MemoryStore | None = None,
        project_root: str | Path | None = None,
    ):
        if not isinstance(project_id, str) or not project_id or len(project_id) > 256:
            raise ValueError("Invalid project ID")
        if (symbol_memory is None) != (project_root is None):
            raise ValueError("Symbol memory and project root must be supplied together")
        self.store = store
        self.project_id = project_id
        self.symbols = (
            SymbolStore(symbol_memory, project_id=project_id, project_root=project_root)
            if symbol_memory is not None and project_root is not None
            else None
        )
        self.initialized = False
        self.ready = False

    def close(self) -> None:
        if self.symbols is not None:
            self.symbols.close()

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
            tools = [TOOL, SYMBOL_TOOL] if self.symbols is not None else [TOOL]
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}}
        if method == "tools/call":
            if params.get("name") == SYMBOL_TOOL_NAME and self.symbols is not None:
                arguments = params.get("arguments", {})
                if (
                    not isinstance(arguments, dict)
                    or not {"query", "snapshot"} <= set(arguments)
                    or set(arguments) - {"query", "snapshot", "limit"}
                    or not isinstance(arguments.get("query"), str)
                    or not isinstance(arguments.get("snapshot"), str)
                    or len(arguments["query"]) > 256
                    or not 0 < len(arguments["snapshot"]) <= 256
                    or ("limit" in arguments and type(arguments["limit"]) is not int)
                    or not 1 <= arguments.get("limit", 20) <= 100
                ):
                    return _error(request_id, -32602, "Invalid tool arguments")
                try:
                    hits = self.symbols.search(
                        arguments["query"], snapshot=arguments["snapshot"],
                        limit=arguments.get("limit", 20),
                    )
                except (ValueError, sqlite3.DatabaseError):
                    return {
                        "jsonrpc": "2.0", "id": request_id,
                        "result": {
                            "content": [{"type": "text", "text": "Symbol index unavailable"}],
                            "isError": True,
                        },
                    }
                return {
                    "jsonrpc": "2.0", "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(
                            {"snapshot": arguments["snapshot"], "hits": hits}, ensure_ascii=False,
                        )}],
                        "isError": False,
                    },
                }
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
    store: ArtifactStore,
    project_id: str,
    input_stream: BinaryIO | None = None,
    output_stream: BinaryIO | None = None,
    *,
    symbol_memory: MemoryStore | None = None,
    project_root: str | Path | None = None,
) -> None:
    """Read one JSON-RPC object per UTF-8 line; stdout contains protocol messages only."""
    source = input_stream if input_stream is not None else sys.stdin.buffer
    sink = output_stream if output_stream is not None else sys.stdout.buffer
    server = RecoveryServer(
        store, project_id, symbol_memory=symbol_memory, project_root=project_root,
    )
    try:
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
    finally:
        server.close()


def main() -> None:
    """Entry point for `python -m julius.mcp_recovery ROOT PROJECT_ID`."""
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m julius.mcp_recovery ARTIFACT_ROOT PROJECT_ID")
    serve_stdio(ArtifactStore(Path(sys.argv[1])), sys.argv[2])


if __name__ == "__main__":
    main()
