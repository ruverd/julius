"""Pure, additive output for documented Codex context hooks.

This module does not install hooks, read transcripts, or modify tool calls.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


ContextEvent = Literal["SessionStart", "UserPromptSubmit"]
SUPPORTED_CONTEXT_EVENTS: tuple[ContextEvent, ...] = ("SessionStart", "UserPromptSubmit")
MAX_CONTEXT_CHARS = 8_000


class CodexHookInput(BaseModel):
    """Fields required to identify one documented Codex context event."""

    model_config = ConfigDict(extra="allow", strict=True)

    hook_event_name: ContextEvent
    session_id: str = Field(min_length=1)
    cwd: str = Field(min_length=1)
    source: Literal["startup", "resume", "clear", "compact"] | None = None
    prompt: str | None = None


def additive_context_output(
    event: Any, context: str | None, *, trusted_context: bool = False
) -> dict[str, Any]:
    """Return only documented additionalContext, or an empty no-op response.

    Unknown and malformed input fails open with no output. The caller supplies
    trusted context explicitly selected by the caller. Raw prompt, transcript,
    document, and tool-output text must not be promoted to developer context.
    The hook never optimizes or replaces a user's prompt. Approval and tool
    decisions remain Codex-owned.
    """

    try:
        parsed = CodexHookInput.model_validate(event)
    except ValidationError:
        return {}
    if parsed.hook_event_name == "SessionStart" and parsed.source is None:
        return {}
    if parsed.hook_event_name == "UserPromptSubmit" and parsed.prompt is None:
        return {}
    if not trusted_context or not isinstance(context, str) or not context.strip():
        return {}
    bounded_context = context[:MAX_CONTEXT_CHARS]
    return {
        "hookSpecificOutput": {
            "hookEventName": parsed.hook_event_name,
            "additionalContext": bounded_context,
        }
    }
