"""Project-scoped, expiring originals stored with private filesystem modes."""

from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

MAX_BYTES = 1024 * 1024
MAX_TTL_MS = 30 * 24 * 60 * 60 * 1000
MAX_EXPORT_BYTES = 16 * MAX_BYTES
MAX_EXPORT_ITEMS = 32
_ID = re.compile(r"[a-f0-9-]{36}\Z")


class ArtifactStore:
    def __init__(self, root: str | Path):
        path = Path(root).absolute()
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.is_symlink():
            raise ValueError("Artifact root is a symlink")
        self.root = path.resolve()

    def _paths(self, project_id: str, artifact_id: str):
        if not isinstance(project_id, str) or not project_id or len(project_id) > 256:
            raise ValueError("Invalid project ID")
        if not isinstance(artifact_id, str) or not _ID.fullmatch(artifact_id):
            raise ValueError("Invalid artifact ID")
        directory = self.root / hashlib.sha256(project_id.encode()).hexdigest()
        if directory.is_symlink():
            raise ValueError("Artifact directory is a symlink")
        directory.mkdir(mode=0o700, exist_ok=True)
        return directory / f"{artifact_id}.txt", directory / f"{artifact_id}.json"

    @staticmethod
    def _read(path: Path) -> str:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_mode & 0o077
                or info.st_size > MAX_BYTES + 1024
            ):
                raise ValueError("Unsafe artifact file")
            with os.fdopen(os.dup(fd), "r", encoding="utf-8") as stream:
                return stream.read()
        finally:
            os.close(fd)

    @staticmethod
    def _metadata(raw: str, project_id: str, artifact_id: str) -> dict:
        metadata = json.loads(raw)
        try:
            created = datetime.fromisoformat(metadata["createdAt"].replace("Z", "+00:00"))
            expires = datetime.fromisoformat(metadata["expiresAt"].replace("Z", "+00:00"))
            valid = (
                metadata["id"] == artifact_id
                and metadata["projectId"] == project_id
                and type(metadata["bytes"]) is int
                and 0 <= metadata["bytes"] <= MAX_BYTES
                and re.fullmatch(r"[a-f0-9]{64}", metadata["sha256"])
                and created.tzinfo is not None
                and expires.tzinfo is not None
                and timedelta(0) < expires - created <= timedelta(milliseconds=MAX_TTL_MS)
            )
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError("Invalid artifact metadata")
        return metadata

    def put(self, project_id: str, content: str, ttl_ms: int | None = None) -> dict:
        if not isinstance(content, str):
            raise TypeError("Content must be a string")
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_BYTES:
            raise ValueError("Artifact too large")
        ttl = 24 * 60 * 60 * 1000 if ttl_ms is None else ttl_ms
        if type(ttl) is not int or not 0 < ttl <= MAX_TTL_MS:
            raise ValueError("Invalid TTL")
        artifact_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        metadata = {
            "id": artifact_id,
            "projectId": project_id,
            "bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "createdAt": now.isoformat().replace("+00:00", "Z"),
            "expiresAt": (now + timedelta(milliseconds=ttl)).isoformat().replace("+00:00", "Z"),
        }
        body, meta = self._paths(project_id, artifact_id)
        for path, data in ((body, encoded), (meta, json.dumps(metadata).encode())):
            fd = os.open(
                path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
            )
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
        return metadata

    def get(self, project_id: str, artifact_id: str) -> str:
        body, meta = self._paths(project_id, artifact_id)
        metadata = self._metadata(self._read(meta), project_id, artifact_id)
        if datetime.fromisoformat(metadata["expiresAt"].replace("Z", "+00:00")) <= datetime.now(
            timezone.utc
        ):
            raise ValueError("Artifact expired")
        content = self._read(body)
        encoded = content.encode()
        if (
            len(encoded) != metadata["bytes"]
            or hashlib.sha256(encoded).hexdigest() != metadata["sha256"]
        ):
            raise ValueError("Artifact integrity mismatch")
        return content

    def delete(self, project_id: str, artifact_id: str) -> None:
        body, meta = self._paths(project_id, artifact_id)
        self._metadata(self._read(meta), project_id, artifact_id)
        self._read(body)
        body.unlink()
        meta.unlink()

    def purge_expired(self, project_id: str) -> int:
        directory = self.root / hashlib.sha256(project_id.encode()).hexdigest()
        if not directory.exists():
            return 0
        if directory.is_symlink():
            raise ValueError("Artifact directory is a symlink")
        removed = 0
        for meta in directory.glob("*.json"):
            artifact_id = meta.stem
            body, metadata_path = self._paths(project_id, artifact_id)
            metadata = self._metadata(self._read(metadata_path), project_id, artifact_id)
            if datetime.fromisoformat(metadata["expiresAt"].replace("Z", "+00:00")) <= datetime.now(
                timezone.utc
            ):
                self._read(body)
                body.unlink()
                metadata_path.unlink()
                removed += 1
        return removed

    def export(
        self,
        project_id: str,
        destination: str | Path,
        artifact_ids: list[str],
        *,
        authorized: bool = False,
        include_raw: bool = False,
    ) -> dict:
        """Export verified artifacts into a new private directory.

        Authorization must be supplied by the caller for this specific export.
        The default manifest contains metadata only; raw content requires opt-in.
        """
        if authorized is not True:
            raise PermissionError("Artifact export requires user authorization")
        if type(include_raw) is not bool:
            raise ValueError("Invalid raw export option")
        if not isinstance(artifact_ids, list) or not 0 < len(artifact_ids) <= MAX_EXPORT_ITEMS:
            raise ValueError("Invalid artifact selection")
        if any(not isinstance(item, str) or not _ID.fullmatch(item) for item in artifact_ids):
            raise ValueError("Invalid artifact ID")
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("Duplicate artifact ID")

        entries = []
        contents = []
        total_bytes = 0
        for artifact_id in artifact_ids:
            body, meta = self._paths(project_id, artifact_id)
            metadata = self._metadata(self._read(meta), project_id, artifact_id)
            content = self.get(project_id, artifact_id)
            total_bytes += metadata["bytes"]
            if total_bytes > MAX_EXPORT_BYTES:
                raise ValueError("Artifact export too large")
            entry = {key: metadata[key] for key in (
                "id", "projectId", "bytes", "sha256", "createdAt", "expiresAt"
            )}
            if include_raw:
                entry["file"] = f"{artifact_id}.txt"
                contents.append((entry["file"], content.encode("utf-8")))
            entries.append(entry)

        manifest = {
            "format": "julius-artifacts-v1",
            "projectId": project_id,
            "includesRaw": include_raw,
            "artifacts": entries,
        }
        target = Path(destination).absolute()
        if target.is_symlink():
            raise ValueError("Export destination is a symlink")
        target.mkdir(mode=0o700, parents=False, exist_ok=False)
        try:
            for name, data in [
                ("manifest.json", json.dumps(manifest, sort_keys=True).encode("utf-8")),
                *contents,
            ]:
                fd = os.open(
                    target / name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
        except Exception:
            for path in target.iterdir():
                path.unlink()
            target.rmdir()
            raise
        return manifest
