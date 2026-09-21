"""Opt-in synthetic Codex UserPromptSubmit acceptance probe."""

from __future__ import annotations

import json
import secrets
import shlex
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .codex_live_probe import MAX_JSONL_BYTES, TIMEOUT_SECONDS, parse_codex_jsonl

MAX_STDERR_BYTES = 65_536
def _hook_script(invocation: Path, marker: str) -> str:
    context = json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": f"Reply with exactly {marker}. Do not use tools.",
    }}, separators=(",", ":"))
    return (
        "#!/bin/sh\nset -eu\n"
        f"printf invoked > {shlex.quote(str(invocation))}\n"
        f"printf '%s\\n' {shlex.quote(context)}\n"
    )



def _marker_observed(raw: bytes, marker: str) -> bool:
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except (UnicodeError, json.JSONDecodeError):
            return False
        if not isinstance(event, dict) or event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            if isinstance(item.get("text"), str) and item["text"].strip() == marker:
                return True
    return False


def probe_codex_hook(
    *,
    confirmed: bool = False,
    executable: str = "codex",
    runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> dict[str, Any]:
    """Run one user-authorized Codex turn with a temporary, inert hook."""
    if confirmed is not True:
        raise ValueError("Live Codex hook probe requires explicit confirmation")
    if not isinstance(executable, str) or not executable:
        raise ValueError("Invalid Codex executable")
    marker = "JULIUS_HOOK_" + secrets.token_hex(12).upper()
    with tempfile.TemporaryDirectory(prefix="julius-codex-hook-probe-") as directory:
        root = Path(directory)
        script = root / "hook.sh"
        invocation = root / "invoked"
        script.write_text(_hook_script(invocation, marker), encoding="utf-8")
        script.chmod(0o700)
        hook_command = shlex.quote(str(script))
        # The -c value is a single TOML value, not a config file or project mutation.
        hook_config = (
            "hooks.UserPromptSubmit=[{hooks=[{type=\"command\",command="
            + json.dumps(hook_command) + ",timeout=5}]}]"
        )
        command = [
            executable, "exec", "--json", "--ephemeral", "--sandbox", "read-only",
            "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
            "--dangerously-bypass-hook-trust", "-c", hook_config,
            "Reply with the exact token supplied by additional developer context. "
            "Do not use tools or inspect files.",
        ]
        try:
            result = runner(
                command, cwd=directory, capture_output=True, timeout=TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "hookInvoked": invocation.is_file(),
                    "markerObserved": None, "usage": None}
        except OSError:
            return {"status": "unavailable", "hookInvoked": invocation.is_file(),
                    "markerObserved": None, "usage": None}
        invoked = invocation.is_file() and invocation.read_text(encoding="utf-8") == "invoked"
        if (not isinstance(result.stdout, bytes) or len(result.stdout) > MAX_JSONL_BYTES
                or not isinstance(result.stderr, bytes) or len(result.stderr) > MAX_STDERR_BYTES):
            return {"status": "invalid_output", "hookInvoked": invoked,
                    "markerObserved": None, "usage": None}
        try:
            usage = parse_codex_jsonl(result.stdout)
            observed = _marker_observed(result.stdout, marker)
        except ValueError:
            return {"status": "invalid_output", "hookInvoked": invoked,
                    "markerObserved": None, "usage": None}
    complete = result.returncode == 0 and usage["turnCompleted"] and not usage["failed"]
    status = "accepted" if complete and invoked and observed else "incomplete"
    return {"status": status, "hookInvoked": invoked,
            "markerObserved": observed if complete else None, "usage": usage}
