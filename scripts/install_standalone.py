"""Preview or apply a local standalone Julius install, update, rollback, or removal."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import tarfile
import tempfile


STATE_NAME = ".julius-install.json"
BACKUP_NAME = ".julius-backups"
MAX_BINARY_BYTES = 250_000_000
MAX_INSTALLER_BYTES = 200_000
MAX_MANIFEST_BYTES = 65_536


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_archive(path: Path) -> tuple[dict, bytes]:
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        expected_sizes = {
            "manifest.json": MAX_MANIFEST_BYTES,
            "julius": MAX_BINARY_BYTES,
            "install_standalone.py": MAX_INSTALLER_BYTES,
        }
        if (
            len(members) != len(expected_sizes)
            or {m.name for m in members} != set(expected_sizes)
            or any(not m.isfile() or m.size < 0 or m.size > expected_sizes[m.name]
                   for m in members)
        ):
            raise ValueError("unexpected archive contents")
        contents = {}
        for member in members:
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("missing archive member")
            data = stream.read(member.size + 1)
            if len(data) != member.size:
                raise ValueError("truncated archive member")
            contents[member.name] = data
    manifest = json.loads(contents["manifest.json"])
    if manifest.get("schema") != 1 or manifest.get("product") != "julius":
        raise ValueError("unsupported manifest")
    if manifest.get("platform") != platform.system().lower() or manifest.get("architecture") != platform.machine().lower():
        raise ValueError("archive platform or architecture does not match this machine")
    if not isinstance(manifest.get("version"), str) or not manifest["version"]:
        raise ValueError("invalid version")
    if manifest.get("files") != {name: digest(contents[name]) for name in ("julius", "install_standalone.py")}:
        raise ValueError("archive SHA-256 mismatch")
    return manifest, contents["julius"]


def regular_or_absent(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"refusing symlink or non-file: {path}")


def write_atomic(path: Path, data: bytes, mode: int) -> None:
    regular_or_absent(path)
    fd, temp = tempfile.mkstemp(prefix=".julius-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def execute(action: str, prefix: Path, archive: Path | None, apply: bool) -> str:
    if prefix.is_symlink() or (prefix.exists() and not prefix.is_dir()):
        raise ValueError("prefix must be a directory, not a symlink")
    bin_dir = prefix / "bin"
    backups = prefix / BACKUP_NAME
    state_path = prefix / STATE_NAME
    binary_path = bin_dir / "julius"
    for item in (bin_dir, backups):
        if item.is_symlink() or (item.exists() and not item.is_dir()):
            raise ValueError(f"refusing symlink or non-directory: {item}")
    regular_or_absent(state_path)
    regular_or_absent(binary_path)
    state = json.loads(state_path.read_text()) if state_path.exists() else None
    if state is not None:
        if state.get("schema") != 1 or state.get("current", {}).get("hash") is None or not isinstance(state.get("history"), list):
            raise ValueError("invalid managed state")
        if not binary_path.exists() or digest(binary_path.read_bytes()) != state["current"]["hash"]:
            raise ValueError("managed binary was modified; refusing operation")
    elif binary_path.exists():
        raise ValueError("unmanaged Julius binary exists; refusing operation")
    elif backups.exists():
        raise ValueError("unmanaged backup directory exists; refusing operation")
    manifest = None
    payload = None
    if action in ("install", "update"):
        if archive is None:
            raise ValueError("--archive is required")
        manifest, payload = load_archive(archive)
        if action == "install" and state is not None:
            raise ValueError("already installed; use update")
        if action == "update" and state is None:
            raise ValueError("nothing installed; use install")
        if state is not None and state["current"]["hash"] == manifest["files"]["julius"] and state["current"]["version"] == manifest["version"]:
            return "Already at requested version; no changes."
        description = f"{action} Julius {manifest['version']} at {binary_path}"
    elif action == "rollback":
        if state is None or not state["history"]:
            return "No previous managed version; no changes."
        prior = state["history"][-1]
        backup_path = backups / prior["hash"]
        regular_or_absent(backup_path)
        if not backup_path.exists() or digest(backup_path.read_bytes()) != prior["hash"]:
            raise ValueError("previous-version backup missing or modified")
        payload = backup_path.read_bytes()
        description = f"rollback Julius to {prior['version']} at {binary_path}"
    elif action == "remove":
        if state is None:
            return "No managed installation; no changes."
        description = f"remove managed Julius at {binary_path}"
    else:
        raise ValueError("unknown action")
    if not apply:
        return f"Preview: {description}. Re-run with --apply."
    prefix.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(exist_ok=True)
    backups.mkdir(exist_ok=True)
    if action in ("update", "rollback"):
        old = state["current"]
        backup_path = backups / old["hash"]
        regular_or_absent(backup_path)
        if backup_path.exists():
            if digest(backup_path.read_bytes()) != old["hash"]:
                raise ValueError("managed backup was modified")
        else:
            write_atomic(backup_path, binary_path.read_bytes(), 0o600)
    if action in ("install", "update"):
        next_current = {"version": manifest["version"], "hash": manifest["files"]["julius"]}
        history = ([] if state is None else state["history"] + [state["current"]])
    elif action == "rollback":
        next_current = state["history"][-1]
        history = state["history"][:-1]
    else:
        for backup in backups.iterdir():
            regular_or_absent(backup)
            if not backup.is_file() or digest(backup.read_bytes()) != backup.name:
                raise ValueError("unrecognized or modified file in managed backup directory")
        binary_path.unlink()
        state_path.unlink()
        for backup in backups.iterdir():
            backup.unlink()
        backups.rmdir()
        return f"Applied: {description}."
    write_atomic(binary_path, payload, 0o755)
    write_atomic(state_path, (json.dumps({"schema": 1, "current": next_current, "history": history}, sort_keys=True, indent=2) + "\n").encode(), 0o600)
    return f"Applied: {description}."


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "update", "rollback", "remove"))
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--prefix", type=Path, default=Path.home() / ".local")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        print(execute(args.action, args.prefix, args.archive, args.apply))
    except (OSError, ValueError, json.JSONDecodeError, tarfile.TarError) as exc:
        parser.exit(2, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
