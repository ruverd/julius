"""Explicit, reversible management of one local configuration file."""

from __future__ import annotations

from dataclasses import dataclass
import difflib
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any


@dataclass(frozen=True)
class ConfigPlan:
    target: Path
    expected_sha256: str | None
    desired_sha256: str
    desired: bytes
    diff: str


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_path(path: Path, root: Path) -> Path:
    if ".." in path.parts:
        raise ValueError("Parent traversal in configuration path")
    path = path.absolute()
    root = root.absolute()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("Configuration target is outside the allowed directory")
    candidate = Path(root.anchor)
    for part in (*root.parts[1:], *path.relative_to(root).parts):
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError("Symlink in configuration path")
    if not root.is_dir() or not path.parent.is_dir():
        raise ValueError("Configuration directory does not exist")
    return path


def _read(path: Path) -> tuple[bytes | None, int | None]:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return None, None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Unsafe configuration file")
        with os.fdopen(os.dup(fd), "rb") as stream:
            return stream.read(), stat.S_IMODE(info.st_mode)
    finally:
        os.close(fd)


def _atomic(path: Path, data: bytes, mode: int) -> None:
    fd, name = tempfile.mkstemp(prefix=".julius-", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class ManagedConfig:
    """Manage targets beneath an explicit root, with private state elsewhere."""

    def __init__(self, allowed_root: str | Path, state_root: str | Path):
        self.allowed_root = Path(allowed_root).absolute()
        self.state_root = Path(state_root).absolute()
        if self.allowed_root.is_symlink() or not self.allowed_root.is_dir():
            raise ValueError("Unsafe allowed directory")
        if self.state_root == self.allowed_root or self.state_root.is_relative_to(
            self.allowed_root
        ):
            raise ValueError("State directory must be separate from configuration")
        if self.state_root.is_symlink():
            raise ValueError("Symlink state directory")
        self.state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if stat.S_IMODE(self.state_root.stat().st_mode) & 0o077:
            raise ValueError("State directory must be private")

    def _paths(self, target: Path) -> tuple[Path, Path]:
        key = _hash(str(target).encode())
        return self.state_root / f"{key}.json", self.state_root / f"{key}.bak"

    def _manifest(self, target: Path) -> dict[str, Any] | None:
        manifest, backup = self._paths(target)
        raw, mode = _read(manifest)
        if raw is None:
            if backup.exists() or backup.is_symlink():
                raise ValueError("Orphaned managed configuration backup")
            return None
        if mode != 0o600:
            raise ValueError("Unsafe manifest permissions")
        try:
            value = json.loads(raw)
            if (
                value["target"] != str(target)
                or not isinstance(value["original_sha256"], (str, type(None)))
                or not isinstance(value["managed_sha256"], str)
                or not isinstance(value["original_mode"], (int, type(None)))
            ):
                raise ValueError("Invalid manifest")
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError("Invalid manifest") from exc
        original, backup_mode = _read(backup)
        if original is None or backup_mode != 0o600:
            raise ValueError("Missing or unsafe backup")
        if value["original_sha256"] != (None if value["original_mode"] is None else _hash(original)):
            raise ValueError("Backup integrity mismatch")
        return value

    def plan(self, target: str | Path, desired: bytes) -> ConfigPlan:
        target = _safe_path(Path(target), self.allowed_root)
        if not isinstance(desired, bytes):
            raise TypeError("Desired configuration must be bytes")
        current, _ = _read(target)
        current_hash = None if current is None else _hash(current)
        old_lines = (current or b"").decode("utf-8", errors="replace").splitlines(keepends=True)
        new_lines = desired.decode("utf-8", errors="replace").splitlines(keepends=True)
        diff = "".join(difflib.unified_diff(old_lines, new_lines, fromfile=str(target), tofile=str(target)))
        return ConfigPlan(target, current_hash, _hash(desired), desired, diff)

    def apply(self, plan: ConfigPlan) -> bool:
        """Apply a previously reviewed plan; return False when already applied."""
        target = _safe_path(plan.target, self.allowed_root)
        current, mode = _read(target)
        current_hash = None if current is None else _hash(current)
        existing = self._manifest(target)
        if existing is not None:
            if current_hash == existing["managed_sha256"] == plan.desired_sha256:
                return False
            raise ValueError("Configuration already managed or changed")
        if current_hash != plan.expected_sha256 or _hash(plan.desired) != plan.desired_sha256:
            raise ValueError("Configuration changed since plan")
        if current == plan.desired:
            return False
        manifest, backup = self._paths(target)
        backup_fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(backup_fd, "wb") as stream:
                stream.write(current or b"")
                stream.flush()
                os.fsync(stream.fileno())
            record = {"target": str(target), "original_sha256": current_hash,
                      "original_mode": mode, "managed_sha256": plan.desired_sha256}
            _atomic(manifest, json.dumps(record, sort_keys=True).encode(), 0o600)
            latest, _ = _read(target)
            if (None if latest is None else _hash(latest)) != current_hash:
                raise ValueError("Configuration changed while applying plan")
            _atomic(target, plan.desired, mode if mode is not None else 0o600)
        except BaseException:
            # Keep recovery data if replacement might have completed before an error.
            latest, _ = _read(target)
            if latest != plan.desired:
                manifest.unlink(missing_ok=True)
                backup.unlink(missing_ok=True)
            raise
        return True

    def remove(self, target: str | Path) -> bool:
        """Restore exact prior bytes/mode only while the managed file is unchanged."""
        target = _safe_path(Path(target), self.allowed_root)
        record = self._manifest(target)
        if record is None:
            return False
        current, _ = _read(target)
        if current is None or _hash(current) != record["managed_sha256"]:
            raise ValueError("Managed configuration changed; refusing restore")
        manifest, backup = self._paths(target)
        original, _ = _read(backup)
        assert original is not None
        latest, _ = _read(target)
        if latest is None or _hash(latest) != record["managed_sha256"]:
            raise ValueError("Managed configuration changed; refusing restore")
        if record["original_mode"] is None:
            target.unlink()
        else:
            _atomic(target, original, record["original_mode"])
        manifest.unlink()
        backup.unlink()
        return True
