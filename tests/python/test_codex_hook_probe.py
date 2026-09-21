import json
import subprocess
import shlex
import tomllib
from pathlib import Path

import pytest

from julius.codex_hook_probe import probe_codex_hook


def test_requires_opt_in() -> None:
    with pytest.raises(ValueError):
        probe_codex_hook()


def test_additive_hook_and_marker_observed() -> None:
    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert command[:3] == ["codex", "exec", "--json"]
        assert "--ignore-user-config" in command
        assert "--dangerously-bypass-hook-trust" in command
        config = command[command.index("-c") + 1]
        assert config.startswith("hooks.UserPromptSubmit=")
        hook = tomllib.loads(config)["hooks"]["UserPromptSubmit"][0]["hooks"][0]
        assert hook["type"] == "command"
        hook_command = shlex.split(hook["command"])
        assert len(hook_command) == 1
        assert Path(hook_command[0]).stat().st_mode & 0o111
        hook_result = subprocess.run(hook_command, cwd=kwargs["cwd"], capture_output=True, check=True)
        context = json.loads(hook_result.stdout)
        token = context["hookSpecificOutput"]["additionalContext"].split()[3].rstrip(".")
        events = [
            {"type": "item.completed", "item": {"type": "agent_message", "text": token}},
            {"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 2}},
        ]
        return subprocess.CompletedProcess(command, 0, b"\n".join(json.dumps(x).encode() for x in events), b"")

    result = probe_codex_hook(confirmed=True, runner=runner)
    assert result["status"] == "accepted"
    assert result["hookInvoked"] is True
    assert result["markerObserved"] is True
    assert result["usage"]["inputTokens"] == 5


def test_no_invocation_is_incomplete() -> None:
    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, 0, b'{"type":"turn.completed"}', b"")

    result = probe_codex_hook(confirmed=True, runner=runner)
    assert result["status"] == "incomplete"
    assert result["hookInvoked"] is False
    assert result["markerObserved"] is False


def test_timeout_preserves_unknown_usage() -> None:
    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(command, 30)

    result = probe_codex_hook(confirmed=True, runner=runner)
    assert result == {"status": "timeout", "hookInvoked": False,
                      "markerObserved": None, "usage": None}
