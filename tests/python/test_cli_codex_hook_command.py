"""Installed CLI exposes the bounded Codex hook without model calls."""

import json
import subprocess
import sys


def test_codex_hook_cli_defaults_to_no_op_and_accepts_reviewed_file(tmp_path):
    event = json.dumps({
        "hook_event_name": "UserPromptSubmit", "session_id": "session",
        "cwd": str(tmp_path), "prompt": "Original user prompt",
    }).encode()
    command = [sys.executable, "-m", "julius.cli", "hook", "codex-user-prompt-submit"]
    default = subprocess.run(command, input=event, capture_output=True, check=True, timeout=5)
    assert default.stdout == b"{}\n"
    assert default.stderr == b""

    note = tmp_path / "reviewed.txt"
    note.write_text("Reviewed synthetic marker", encoding="utf-8")
    trusted = subprocess.run(
        [*command, "--trusted-context-file", str(note)],
        input=event, capture_output=True, check=True, timeout=5,
    )
    assert json.loads(trusted.stdout) == {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "Reviewed synthetic marker",
        },
    }
    assert trusted.stderr == b""
