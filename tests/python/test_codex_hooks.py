from julius.codex_hooks import MAX_CONTEXT_CHARS, additive_context_output


def test_user_prompt_receives_additive_context_without_rewriting_prompt() -> None:
    event = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "session-1",
        "cwd": "/tmp/project",
        "prompt": "Keep this original prompt",
        "permission_mode": "default",
    }
    original = event.copy()
    assert additive_context_output(event, "Local note") == {}
    assert additive_context_output(event, "Local note", trusted_context=True) == {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "Local note",
        }
    }
    assert event == original


def test_session_start_receives_additive_context() -> None:
    event = {
        "hook_event_name": "SessionStart",
        "session_id": "session-1",
        "cwd": "/tmp/project",
        "source": "compact",
    }
    assert additive_context_output(event, "Workspace notes", trusted_context=True)[
        "hookSpecificOutput"
    ]["hookEventName"] == (
        "SessionStart"
    )


def test_unsupported_events_and_missing_required_fields_are_no_ops() -> None:
    base = {"session_id": "session-1", "cwd": "/tmp/project"}
    for name in ("PreToolUse", "PermissionRequest", "PostToolUse", "Stop", "Unknown"):
        assert additive_context_output(
            {**base, "hook_event_name": name}, "note", trusted_context=True
        ) == {}
    assert additive_context_output(
        {**base, "hook_event_name": "UserPromptSubmit"}, "note", trusted_context=True
    ) == {}
    assert additive_context_output(
        {**base, "hook_event_name": "SessionStart"}, "note", trusted_context=True
    ) == {}
    assert additive_context_output(
        {**base, "hook_event_name": "UserPromptSubmit", "prompt": "x"}, "", trusted_context=True
    ) == {}


def test_context_is_bounded_and_contains_no_control_decisions() -> None:
    event = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "session-1",
        "cwd": "/tmp/project",
        "prompt": "hello",
    }
    output = additive_context_output(event, "x" * (MAX_CONTEXT_CHARS + 10), trusted_context=True)
    assert len(output["hookSpecificOutput"]["additionalContext"]) == MAX_CONTEXT_CHARS
    assert set(output) == {"hookSpecificOutput"}
    assert set(output["hookSpecificOutput"]) == {"hookEventName", "additionalContext"}
