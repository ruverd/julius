"""Fail-closed local optimization policy."""

from datetime import datetime, timezone
import re


def policy_decision(policy: dict) -> str | None:
    if policy.get("disabled"):
        return "policy_disabled"
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(policy.get("version", ""))):
        return "invalid_policy_version"
    expiry = policy.get("expiresAt")
    if expiry is not None:
        try:
            expires = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
                return "policy_expired"
        except (ValueError, AttributeError):
            return "policy_expired"
    if policy.get("mode") not in ("safe", "observe"):
        return "invalid_policy_mode"
    if policy["mode"] == "safe" and policy.get("approved") is not True:
        return "approval_required"
    return None
