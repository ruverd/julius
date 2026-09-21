"""Version-scoped adapter capability declarations, separate from doctor probes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, model_validator

from . import __version__


class AdapterCapabilities(BaseModel):
    """What Julius has evidence for on one exact client version."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    adapterId: StrictStr = Field(min_length=1)
    adapterVersion: StrictStr = Field(min_length=1)
    clientVersion: StrictStr | None
    status: Literal["tested", "experimental", "observe_only", "unsupported"]
    canObserveUsage: StrictBool
    canReplaceToolOutput: StrictBool
    canObserveCompleteRequest: StrictBool
    canRouteRequests: StrictBool
    canAttributeActualModel: StrictBool
    canAttributeTask: StrictBool
    canPreserveApprovalFlow: StrictBool
    supportedProtocolVersions: tuple[StrictStr, ...]

    @model_validator(mode="after")
    def coherent(self) -> AdapterCapabilities:
        capabilities = (
            self.canObserveUsage, self.canReplaceToolOutput,
            self.canObserveCompleteRequest, self.canRouteRequests,
            self.canAttributeActualModel, self.canAttributeTask,
            self.canPreserveApprovalFlow,
        )
        if self.status == "unsupported" and any(capabilities):
            raise ValueError("Unsupported adapter cannot claim capabilities")
        if self.status == "observe_only" and (
            self.canReplaceToolOutput or self.canRouteRequests
        ):
            raise ValueError("Observe-only adapter cannot claim mutation or routing")
        return self


_EVIDENCE: dict[tuple[str, str], dict[str, Any]] = {
    ("claude", "2.1.278"): {
        "status": "experimental",
        "canObserveUsage": True,
        "canReplaceToolOutput": True,
        "canAttributeActualModel": True,
        "canAttributeTask": True,
    },
    ("codex", "0.154.0"): {
        "status": "observe_only",
        "canObserveUsage": True,
        "canAttributeTask": True,
    },
}


def capabilities_for_client(name: str, client_version: str | None) -> AdapterCapabilities:
    """Return bounded historical evidence; no client invocation happens here."""
    if name not in ("claude", "codex"):
        raise ValueError("Unknown adapter")
    observed = _EVIDENCE.get((name, client_version)) if client_version is not None else None
    declared: dict[str, Any] = {
        "adapterId": "claude-code" if name == "claude" else "codex-cli",
        "adapterVersion": __version__,
        "clientVersion": client_version,
        "status": "unsupported",
        "canObserveUsage": False,
        "canReplaceToolOutput": False,
        "canObserveCompleteRequest": False,
        "canRouteRequests": False,
        "canAttributeActualModel": False,
        "canAttributeTask": False,
        "canPreserveApprovalFlow": False,
        "supportedProtocolVersions": (),
    }
    if observed:
        declared.update(observed)
    return AdapterCapabilities.model_validate(declared)
