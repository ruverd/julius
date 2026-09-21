"""Reversible project-local Codex hook management."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from .codex_config import CodexConfigPlan, plan_codex_project_config
from .managed_config import ConfigPlan, ManagedConfig, _read, _safe_path


@dataclass(frozen=True)
class CodexIntegrationPlan:
    hooks: ConfigPlan
    entry: CodexConfigPlan


class CodexIntegrationManager:
    """Manage only the trusted project's .codex/hooks.json file."""

    def __init__(self, project_root: str | Path, state_root: str | Path):
        self.project_root = Path(project_root).resolve()
        self.hooks_path = self.project_root / ".codex" / "hooks.json"
        if not self.hooks_path.parent.is_dir() or self.hooks_path.parent.is_symlink():
            raise ValueError("Project .codex directory must exist before planning")
        self.managed = ManagedConfig(self.project_root, state_root)

    def preview(self, *, hook_command: str) -> CodexIntegrationPlan:
        path = _safe_path(self.hooks_path, self.project_root)
        current, _ = _read(path)
        record = self.managed._manifest(path)
        if record is not None:
            if current is None or hashlib.sha256(current).hexdigest() != record["managed_sha256"]:
                raise ValueError("Managed configuration changed; refusing repeat plan")
            # Re-create the planned file from the backup, requiring the same command.
            _, backup = self.managed._paths(path)
            original, _ = _read(backup)
            requested = plan_codex_project_config(
                None if record["original_mode"] is None else original,
                hook_command=hook_command,
            )
            if requested.hooks != current:
                raise ValueError("Julius hook command changed; refusing repeat plan")
            return CodexIntegrationPlan(self.managed.plan(path, current), requested)
        entry = plan_codex_project_config(current, hook_command=hook_command)
        return CodexIntegrationPlan(self.managed.plan(path, entry.hooks), entry)

    def apply(self, plan: CodexIntegrationPlan) -> bool:
        if plan.hooks.target != self.hooks_path or plan.hooks.desired != plan.entry.hooks:
            raise ValueError("Plan targets a different Codex configuration")
        return self.managed.apply(plan.hooks)

    def remove(self) -> bool:
        return self.managed.remove(self.hooks_path)
