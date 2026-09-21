"""Pure planner for opt-in Claude project hook and MCP JSON entries."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Any


SERVER_NAME = "julius-recovery"
MAX_CONFIG_BYTES = 1_048_576


@dataclass(frozen=True)
class ClaudeConfigPlan:
    settings: bytes
    mcp: bytes
    hook_entry: dict[str, Any]
    mcp_entry: dict[str, Any]


def _parse(raw: bytes | None, label: str) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, bytes) or len(raw) > MAX_CONFIG_BYTES:
        raise ValueError(f"Invalid {label} bytes")
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid {label} JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _encode(value: dict[str, Any]) -> bytes:
    result = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    if len(result) > MAX_CONFIG_BYTES:
        raise ValueError("Managed configuration exceeds 1 MiB")
    return result


def _hook_groups(settings: dict[str, Any]) -> list[Any]:
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Claude hooks setting is not an object")
    groups = hooks.setdefault("PostToolUse", [])
    if not isinstance(groups, list):
        raise ValueError("Claude PostToolUse setting is not an array")
    return groups


def plan_claude_project_config(
    settings: bytes | None,
    mcp: bytes | None,
    *,
    hook_command: str,
    mcp_command: str,
    mcp_args: list[str],
) -> ClaudeConfigPlan:
    """Prepare two complete desired files; existing Julius entries are collisions."""
    if (
        not isinstance(hook_command, str) or not hook_command.strip()
        or "\n" in hook_command or "\r" in hook_command
        or not isinstance(mcp_command, str) or not mcp_command.strip()
        or not isinstance(mcp_args, list) or any(not isinstance(arg, str) for arg in mcp_args)
    ):
        raise ValueError("Invalid Julius launch command")
    settings_obj = _parse(settings, "settings")
    mcp_obj = _parse(mcp, "MCP")
    groups = _hook_groups(settings_obj)
    if any(not isinstance(group, dict) for group in groups):
        raise ValueError("Invalid Claude PostToolUse group")
    if any(
        isinstance(hook, dict) and "julius" in str(hook.get("command", "")).lower()
        for group in groups for hook in group.get("hooks", [])
        if isinstance(group.get("hooks"), list)
    ):
        raise ValueError("Existing Julius hook requires manual review")
    hook_entry = {"matcher": "Bash", "hooks": [{"type": "command", "command": hook_command}]}
    groups.append(deepcopy(hook_entry))
    servers = mcp_obj.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError("Claude mcpServers setting is not an object")
    if SERVER_NAME in servers:
        raise ValueError("Julius MCP server name already exists")
    mcp_entry = {"type": "stdio", "command": mcp_command, "args": list(mcp_args)}
    servers[SERVER_NAME] = deepcopy(mcp_entry)
    return ClaudeConfigPlan(_encode(settings_obj), _encode(mcp_obj), hook_entry, mcp_entry)


def unmerge_claude_project_config(
    settings: bytes,
    mcp: bytes,
    plan: ClaudeConfigPlan,
) -> tuple[bytes, bytes]:
    """Remove only entries from this plan, refusing missing or changed entries."""
    settings_obj = _parse(settings, "settings")
    mcp_obj = _parse(mcp, "MCP")
    groups = _hook_groups(settings_obj)
    matches = [index for index, group in enumerate(groups) if group == plan.hook_entry]
    if len(matches) != 1:
        raise ValueError("Julius hook missing, duplicated, or changed")
    servers = mcp_obj.get("mcpServers")
    if not isinstance(servers, dict) or servers.get(SERVER_NAME) != plan.mcp_entry:
        raise ValueError("Julius MCP entry missing or changed")
    groups.pop(matches[0])
    if not groups:
        settings_obj["hooks"].pop("PostToolUse")
    if not settings_obj["hooks"]:
        settings_obj.pop("hooks")
    servers.pop(SERVER_NAME)
    if not servers:
        mcp_obj.pop("mcpServers")
    return _encode(settings_obj), _encode(mcp_obj)
