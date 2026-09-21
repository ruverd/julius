"""Offline, fail-closed preparation of xAI Responses tool-output candidates."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping

from .artifacts import ArtifactStore
from .optimizer import optimize

RECOVERY_TOOL = "julius_restore_artifact"


@dataclass(frozen=True)
class PreparedXAIRequest:
    request: dict[str, Any]
    receipts: tuple[dict[str, Any], ...]
    candidate_only: bool = True


def _has_recovery_tool(request: Mapping[str, Any]) -> bool:
    tools = request.get("tools")
    if not isinstance(tools, list):
        return False
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        if tool.get("name") != RECOVERY_TOOL:
            continue
        parameters = tool.get("parameters")
        if not isinstance(parameters, dict) or parameters.get("type") != "object":
            continue
        properties = parameters.get("properties")
        required = parameters.get("required")
        if (isinstance(properties, dict) and isinstance(required, list)
                and properties.get("artifact_id") == {"type": "string"}
                and "artifact_id" in required):
            return True
    return False


def prepare_optimized_request(
    request: Mapping[str, Any],
    *,
    project_id: str,
    policy: dict[str, Any],
    artifacts: ArtifactStore,
    recovery_handler_available: bool = False,
) -> PreparedXAIRequest:
    """Prepare a copy; never send, alter the caller's request, or claim realized savings.

    The caller must actually serve ``julius_restore_artifact`` with the same
    project-scoped ArtifactStore for the lifetime of each retained artifact.
    """
    if not isinstance(request, Mapping):
        raise ValueError("Responses request must be an object")
    inputs = request.get("input")
    if not isinstance(inputs, list) or not all(isinstance(item, dict) for item in inputs):
        raise ValueError("Only Responses array input is supported")
    if not recovery_handler_available or not _has_recovery_tool(request):
        raise ValueError("An available Julius recovery function is required")
    for item in inputs:
        kind = item.get("type")
        if kind == "function_call_output":
            if (not isinstance(item.get("call_id"), str) or not item["call_id"]
                    or not isinstance(item.get("output"), str)):
                raise ValueError("Unsupported function_call_output shape")
        elif kind is None and item.get("role") in ("system", "developer", "user", "assistant"):
            pass
        elif kind == "function_call" and isinstance(item.get("call_id"), str):
            pass
        else:
            raise ValueError("Unsupported Responses input item")
    try:
        candidate_request = copy.deepcopy(dict(request))
    except (TypeError, ValueError) as exc:
        raise ValueError("Request cannot be copied") from exc
    receipts: list[dict[str, Any]] = []
    retained: list[str] = []
    try:
        for index, item in enumerate(inputs):
            if item.get("type") != "function_call_output":
                continue
            original = item["output"]
            artifact = artifacts.put(project_id, original)
            artifact_id = artifact["id"]
            retained.append(artifact_id)
            if artifacts.get(project_id, artifact_id) != original:
                raise ValueError("Original could not be recovered")
            result = optimize(
                {"projectId": project_id, "category": "tool_output", "content": original,
                 "recovery": {"available": True, "artifactId": artifact_id}},
                policy,
            )
            receipt = dict(result["receipt"])
            receipt["inputIndex"] = index
            receipt["callId"] = item["call_id"]
            if receipt["applied"]:
                candidate_request["input"][index]["output"] = result["candidate"]
            else:
                artifacts.delete(project_id, artifact_id)
                retained.remove(artifact_id)
            receipts.append(receipt)
    except BaseException:
        for artifact_id in retained:
            try:
                artifacts.delete(project_id, artifact_id)
            except (OSError, ValueError):
                pass
        raise
    return PreparedXAIRequest(candidate_request, tuple(receipts))
