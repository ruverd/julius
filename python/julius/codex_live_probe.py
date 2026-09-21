"""Explicit synthetic Codex CLI observation probe; never runs on import."""

from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Callable
from typing import Any


PROMPT = "Reply with exactly READY. Do not use tools, inspect files, or change anything."
MAX_JSONL_BYTES = 1_048_576
MAX_EVENTS = 1_000
TIMEOUT_SECONDS = 30


def _count(usage: dict[str, Any], key: str) -> int | None:
    value = usage.get(key)
    return value if type(value) is int and 0 <= value <= 2**53 - 1 else None


def parse_codex_jsonl(raw: bytes | str) -> dict[str, Any]:
    """Extract documented turn usage without retaining messages or tool content."""
    if isinstance(raw, str):
        encoded = raw.encode("utf-8")
    elif isinstance(raw, bytes):
        encoded = raw
    else:
        raise ValueError("Codex JSONL must be bytes or text")
    if len(encoded) > MAX_JSONL_BYTES:
        raise ValueError("Codex JSONL exceeds 1 MiB")
    lines = encoded.splitlines()
    if len(lines) > MAX_EVENTS:
        raise ValueError("Too many Codex events")
    completed: list[dict[str, Any]] = []
    failed = False
    thread_id: str | None = None
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("Invalid Codex JSONL") from error
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise ValueError("Invalid Codex event")
        if event["type"] == "thread.started" and isinstance(event.get("thread_id"), str):
            thread_id = event["thread_id"]
        elif event["type"] == "turn.completed":
            completed.append(event)
        elif event["type"] in ("turn.failed", "error"):
            failed = True
    if len(completed) > 1:
        raise ValueError("Probe produced multiple completed turns")
    usage = completed[0].get("usage") if completed else None
    usage = usage if isinstance(usage, dict) else {}
    return {
        "threadId": thread_id,
        "turnCompleted": len(completed) == 1,
        "failed": failed,
        "inputTokens": _count(usage, "input_tokens"),
        "cachedInputTokens": _count(usage, "cached_input_tokens"),
        "outputTokens": _count(usage, "output_tokens"),
        "reasoningOutputTokens": _count(usage, "reasoning_output_tokens"),
        "evidence": "codex_cli_jsonl" if completed else "unavailable",
    }


def probe_codex_usage(
    *, confirmed: bool = False, executable: str = "codex",
    runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> dict[str, Any]:
    """Run one opted-in read-only Codex turn in an empty temporary directory."""
    if confirmed is not True:
        raise ValueError("Live Codex probe requires explicit confirmation")
    if not isinstance(executable, str) or not executable:
        raise ValueError("Invalid Codex executable")
    command = [
        executable, "exec", "--json", "--ephemeral", "--sandbox", "read-only",
        "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check", PROMPT,
    ]
    with tempfile.TemporaryDirectory(prefix="julius-codex-probe-") as directory:
        try:
            result = runner(
                command, cwd=directory, capture_output=True, timeout=TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "usage": None}
    if not isinstance(result.stdout, bytes) or len(result.stdout) > MAX_JSONL_BYTES:
        return {"status": "invalid_output", "usage": None}
    try:
        usage = parse_codex_jsonl(result.stdout)
    except ValueError:
        return {"status": "invalid_output", "usage": None}
    status = "complete" if result.returncode == 0 and usage["turnCompleted"] and not usage["failed"] else "incomplete"
    return {"status": status, "usage": usage}
