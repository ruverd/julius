"""Pure planner for the opt-in Codex project prompt hook."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Any


MAX_CONFIG_BYTES = 1_048_576


@dataclass(frozen=True)
class CodexConfigPlan:
    hooks: bytes
    hook_entry: dict[str, Any]


def _encode(value: dict[str, Any]) -> bytes:
    result = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    if len(result) > MAX_CONFIG_BYTES:
        raise ValueError("Managed configuration exceeds 1 MiB")
    return result


def _parse(raw: bytes | None) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, bytes) or len(raw) > MAX_CONFIG_BYTES:
        raise ValueError("Invalid Codex hooks bytes")
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid Codex hooks JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Codex hooks must be a JSON object")
    return value


def _groups(value: dict[str, Any]) -> list[Any]:
    hooks = value.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Codex hooks property must be an object")
    for event_groups in hooks.values():
        if not isinstance(event_groups, list):
            raise ValueError("Codex hook events must be arrays")
        for group in event_groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                raise ValueError("Invalid Codex hook group")
            for hook in group["hooks"]:
                if not isinstance(hook, dict):
                    raise ValueError("Invalid Codex hook")
                if "julius" in str(hook.get("command", "")).lower():
                    raise ValueError("Existing Julius hook requires manual review")
    groups = hooks.setdefault("UserPromptSubmit", [])
    return groups


def plan_codex_project_config(raw: bytes | None, *, hook_command: str) -> CodexConfigPlan:
    if (not isinstance(hook_command, str) or not hook_command.strip()
            or "\n" in hook_command or "\r" in hook_command):
        raise ValueError("Invalid Julius hook command")
    value = _parse(raw)
    groups = _groups(value)
    entry = {"hooks": [{"type": "command", "command": hook_command, "timeout": 10}]}
    groups.append(deepcopy(entry))
    return CodexConfigPlan(_encode(value), entry)

