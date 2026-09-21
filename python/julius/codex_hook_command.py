"""Bounded, offline command endpoint for a Codex UserPromptSubmit hook."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import BinaryIO, TextIO

from .codex_hooks import MAX_CONTEXT_CHARS, additive_context_output

MAX_INPUT_BYTES = 65_536
MAX_CONTEXT_BYTES = MAX_CONTEXT_CHARS * 4


def run_user_prompt_submit(
    stdin: BinaryIO,
    stdout: TextIO,
    *,
    context: str | None = None,
    trusted_context: bool = False,
) -> int:
    """Consume one Codex event and emit one JSON response; malformed input is a no-op."""
    output: dict[str, object] = {}
    try:
        raw = stdin.read(MAX_INPUT_BYTES + 1)
        if isinstance(raw, bytes) and len(raw) <= MAX_INPUT_BYTES:
            event = json.loads(raw.decode("utf-8"))
            if isinstance(event, dict) and event.get("hook_event_name") == "UserPromptSubmit":
                output = additive_context_output(
                    event, context, trusted_context=trusted_context
                )
    except (OSError, UnicodeError, ValueError):
        pass
    stdout.write(json.dumps(output, ensure_ascii=False, separators=(",", ":")) + "\n")
    return 0


def _read_trusted_context(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        with path.open("rb") as source:
            raw = source.read(MAX_CONTEXT_BYTES + 1)
        if len(raw) > MAX_CONTEXT_BYTES:
            return None
        return raw.decode("utf-8")
    except (OSError, UnicodeError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Codex UserPromptSubmit hook")
    parser.add_argument(
        "--trusted-context-file",
        type=Path,
        help="operator-reviewed local text to add as developer context",
    )
    args = parser.parse_args(argv)
    context = _read_trusted_context(args.trusted_context_file)
    return run_user_prompt_submit(
        sys.stdin.buffer,
        sys.stdout,
        context=context,
        trusted_context=context is not None and args.trusted_context_file is not None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
