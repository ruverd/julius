"""Pure candidate generation. The native extension only transforms eligible text."""

import re
from .policy import policy_decision

_PROTECTED = re.compile(
    r"\b(error|exception|warning|denied|permission|approval|instruction|system prompt|fail(?:ed|ure)?|assert(?:ion)?|panic|stack trace|traceback)\b",
    re.I,
)
_ARTIFACT = re.compile(r"[a-f0-9-]{36}\Z")


def optimize(context: dict, policy: dict) -> dict:
    content = context.get("content")
    if not isinstance(content, str):
        raise TypeError("Content must be a string")
    before_bytes = len(content.encode("utf-8"))
    if before_bytes > 1024 * 1024:
        raise ValueError("Content too large")
    candidate = content
    reason = policy_decision(policy) or "no_reducible_lines"
    recovery = context.get("recovery")
    if reason == "no_reducible_lines":
        if context.get("category") != "tool_output":
            reason = "ineligible_scope"
        elif (
            context.get("protected")
            or _PROTECTED.search(content)
            or any(ord(char) < 32 and char not in "\n\r\t" for char in content)
            or "```" in content
            or "-----BEGIN " in content
        ):
            reason = "protected_content"
        elif context.get("priorTransformId") and policy.get("allowRecompression") is not True:
            reason = "recompression_requires_opt_in"
        elif policy["mode"] == "observe":
            reason = "observe_mode"
        elif (
            not isinstance(recovery, dict)
            or recovery.get("available") is not True
            or not isinstance(recovery.get("artifactId"), str)
            or not _ARTIFACT.fullmatch(recovery["artifactId"])
        ):
            reason = "recovery_required"
        else:
            try:
                from ._native import compress_repeated_lines
            except ImportError:
                reason = "native_unavailable"
            else:
                candidate = compress_repeated_lines(content, recovery["artifactId"])
                if candidate != content:
                    reason = "repeated_exact_lines"
    after_bytes = len(candidate.encode("utf-8"))
    applied = candidate != content
    return {
        "candidate": candidate,
        "receipt": {
            "scope": "tool_output",
            "applied": applied,
            "reason": reason,
            "policyVersion": policy.get("version"),
            "beforeBytes": before_bytes,
            "afterBytes": after_bytes,
            "beforeTokens": (before_bytes + 3) // 4,
            "afterTokens": (after_bytes + 3) // 4,
            "tokenEstimateMethod": "heuristic_utf8_bytes_divided_by_4",
            "evidence": "heuristic_estimate",
            "tokenizer": None,
            "realizedSavings": None,
            "lineage": {
                "priorTransformId": context.get("priorTransformId"),
                "originalArtifactId": recovery.get("artifactId")
                if applied and isinstance(recovery, dict)
                else None,
            },
        },
    }
