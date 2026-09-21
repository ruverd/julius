"""Opt-in, offline Claude Code PostToolUse adapter for successful Bash output."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

from .artifacts import ArtifactStore
from .optimizer import optimize
from .policy import policy_decision


def post_tool_use(
    event: Mapping[str, Any],
    *,
    policy: dict[str, Any],
    store: ArtifactStore,
    project_id: str,
    recovery_available: bool = False,
    candidate_receipt: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
) -> dict[str, Any] | None:
    """Return a hook response, or None to leave Claude Code's result untouched.

    The caller controls installation and supplies an explicitly approved policy and
    project-scoped local artifact store. A supplied callback receives copies of the
    artifact metadata and optimizer receipt before a replacement is returned.
    No client settings or network are touched by this adapter.
    """
    if recovery_available is not True:
        return None
    if policy_decision(policy) is not None or policy.get("mode") != "safe":
        return None
    if event.get("hook_event_name") != "PostToolUse" or event.get("tool_name") != "Bash":
        return None
    if not isinstance(event.get("tool_input"), dict):
        return None
    response = event.get("tool_response")
    if not isinstance(response, dict):
        return None
    stdout = response.get("stdout")
    if (
        not isinstance(stdout, str)
        or not stdout
        or not isinstance(response.get("stderr"), str)
        or response["stderr"]
        or response.get("interrupted") is not False
        or response.get("isImage") is not False
        or response.get("exitCode", 0) != 0
        or response.get("exit_code", 0) != 0
    ):
        return None
    artifact_id: str | None = None
    try:
        artifact = store.put(project_id, stdout)
        artifact_id = artifact["id"]
        result = optimize(
            {
                "content": stdout,
                "category": "tool_output",
                "recovery": {"available": True, "artifactId": artifact["id"]},
            },
            policy,
        )
        if not result["receipt"]["applied"]:
            store.delete(project_id, artifact["id"])
            return None
        # Verify recovery before returning a replacement. Keep every response field.
        if store.get(project_id, artifact["id"]) != stdout:
            store.delete(project_id, artifact["id"])
            return None
        if candidate_receipt is not None:
            candidate_receipt(deepcopy(artifact), deepcopy(result["receipt"]))
    except Exception:
        if artifact_id is not None:
            try:
                store.delete(project_id, artifact_id)
            except (OSError, ValueError, TypeError):
                pass
        return None
    updated = dict(response)
    updated["stdout"] = result["candidate"]
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "updatedToolOutput": updated,
        }
    }
