import io
import json
import subprocess
import sys

from julius.codex_hook_command import MAX_INPUT_BYTES, run_user_prompt_submit


EVENT = {
    "hook_event_name": "UserPromptSubmit",
    "session_id": "session-1",
    "cwd": "/tmp/project",
    "prompt": "Leave my prompt unchanged",
    "permission_mode": "default",
}


def invoke(raw: bytes, *, context: str | None = None, trusted: bool = False) -> dict:
    stdout = io.StringIO()
    assert run_user_prompt_submit(
        io.BytesIO(raw), stdout, context=context, trusted_context=trusted
    ) == 0
    assert stdout.getvalue().endswith("\n")
    return json.loads(stdout.getvalue())


def test_explicit_trusted_context_only_adds_context() -> None:
    raw = json.dumps(EVENT).encode()
    assert invoke(raw, context="Reviewed instruction") == {}
    assert invoke(raw, context="Reviewed instruction", trusted=True) == {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "Reviewed instruction",
        }
    }


def test_invalid_and_oversized_input_fail_open() -> None:
    for raw in (b"", b"not JSON", b"\xff", b"[1,2]", b"x" * (MAX_INPUT_BYTES + 1)):
        assert invoke(raw, context="Reviewed", trusted=True) == {}
    assert invoke(json.dumps({**EVENT, "hook_event_name": "PreToolUse"}).encode(),
                  context="Reviewed", trusted=True) == {}


def test_executable_defaults_to_no_op_and_accepts_reviewed_file(tmp_path) -> None:
    note = tmp_path / "reviewed.txt"
    note.write_text("Reviewed local convention", encoding="utf-8")
    command = [sys.executable, "-m", "julius.codex_hook_command"]
    raw = json.dumps(EVENT).encode()
    default = subprocess.run(command, input=raw, capture_output=True, check=True)
    assert default.stdout == b"{}\n"
    assert default.stderr == b""
    explicit = subprocess.run(
        [*command, "--trusted-context-file", str(note)],
        input=raw, capture_output=True, check=True,
    )
    assert json.loads(explicit.stdout)["hookSpecificOutput"]["additionalContext"] == (
        "Reviewed local convention"
    )
    assert explicit.stderr == b""
