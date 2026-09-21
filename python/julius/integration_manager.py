"""Explicit preview/apply/remove of Claude project-local Julius configuration."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from .claude_config import ClaudeConfigPlan, plan_claude_project_config
from .managed_config import ConfigPlan, ManagedConfig, _read, _safe_path


@dataclass(frozen=True)
class IntegrationPlan:
    settings: ConfigPlan
    mcp: ConfigPlan
    entries: ClaudeConfigPlan


class ClaudeIntegrationManager:
    """Manage two fixed project files without changing global client settings."""

    def __init__(self, project_root: str | Path, state_root: str | Path):
        self.project_root = Path(project_root).absolute()
        self.settings_path = self.project_root / ".claude" / "settings.json"
        self.mcp_path = self.project_root / ".mcp.json"
        if not self.settings_path.parent.is_dir():
            raise ValueError("Project .claude directory must exist before planning")
        self.managed = ManagedConfig(self.project_root, state_root)

    def preview(
        self, *, hook_command: str, mcp_command: str, mcp_args: list[str],
        recovery_verified: bool = False,
    ) -> IntegrationPlan:
        """Return reviewable diffs and desired bytes without writing project files."""
        if "--recovery-available" in hook_command and recovery_verified is not True:
            raise ValueError("Recovery flag requires a verified client-accessible recovery tool")
        current_settings, _ = _read(_safe_path(self.settings_path, self.project_root))
        current_mcp, _ = _read(_safe_path(self.mcp_path, self.project_root))
        entries = plan_claude_project_config(
            current_settings, current_mcp, hook_command=hook_command,
            mcp_command=mcp_command, mcp_args=mcp_args,
        )
        return IntegrationPlan(
            self.managed.plan(self.settings_path, entries.settings),
            self.managed.plan(self.mcp_path, entries.mcp), entries,
        )

    def apply(self, plan: IntegrationPlan) -> bool:
        """Apply a reviewed plan, rolling back the hook if MCP installation fails."""
        if plan.settings.target != self.settings_path or plan.mcp.target != self.mcp_path:
            raise ValueError("Plan targets a different project")
        manifests = [self.managed._manifest(path) for path in (self.settings_path, self.mcp_path)]
        if any(record is None for record in manifests) and any(record is not None for record in manifests):
            raise ValueError("Incomplete managed integration; manual review required")
        # Check both expected states before the first write.
        for item in (plan.settings, plan.mcp):
            current, _ = _read(_safe_path(item.target, self.project_root))
            digest = None if current is None else hashlib.sha256(current).hexdigest()
            if digest != item.expected_sha256 and digest != item.desired_sha256:
                raise ValueError("Project configuration changed since preview")
            if digest == item.desired_sha256 and all(record is None for record in manifests):
                raise ValueError("Desired configuration exists without a managed backup")
        changed_settings = self.managed.apply(plan.settings)
        try:
            changed_mcp = self.managed.apply(plan.mcp)
        except BaseException:
            if changed_settings:
                self.managed.remove(self.settings_path)
            raise
        return changed_settings or changed_mcp

    def remove(self) -> bool:
        """Restore backed-up bytes only when both managed files are unchanged."""
        records = [self.managed._manifest(path) for path in (self.settings_path, self.mcp_path)]
        if records == [None, None]:
            return False
        if any(record is None for record in records):
            raise ValueError("Incomplete managed integration; manual review required")
        for path, record in zip((self.settings_path, self.mcp_path), records, strict=True):
            assert record is not None
            current, _ = _read(_safe_path(path, self.project_root))
            if current is None or hashlib.sha256(current).hexdigest() != record["managed_sha256"]:
                raise ValueError("Managed configuration changed; refusing removal")
        # Remove the hook first so an MCP removal failure leaves no active rewrite.
        self.managed.remove(self.settings_path)
        self.managed.remove(self.mcp_path)
        return True
