from pathlib import Path
import hashlib
import json
import time

import pytest

from julius.artifacts import ArtifactStore
import julius.artifacts as artifact_module


def test_artifact_recovery_project_isolation_and_integrity(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")
    item = store.put("one", "original")
    assert store.get("one", item["id"]) == "original"
    with pytest.raises(FileNotFoundError):
        store.get("two", item["id"])
    directory = store.root / hashlib.sha256(b"one").hexdigest()
    (directory / f"{item['id']}.txt").write_text("altered!")
    with pytest.raises(ValueError, match="integrity"):
        store.get("one", item["id"])
    metadata_path = directory / f"{item['id']}.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["expiresAt"] = "invalid"
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="metadata"):
        store.get("one", item["id"])


def test_expiry_purge_and_symlink(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")
    item = store.put("one", "short", ttl_ms=1)
    time.sleep(0.005)
    with pytest.raises(ValueError, match="expired"):
        store.get("one", item["id"])
    assert store.purge_expired("one") == 1
    assert store.purge_expired("one") == 0
    outside = tmp_path / "outside"
    outside.mkdir()
    (store.root / hashlib.sha256(b"other").hexdigest()).symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        store.put("other", "secret")
    with pytest.raises(ValueError, match="ID"):
        store.get("one", "../escape")
    with pytest.raises(ValueError, match="TTL"):
        store.put("one", "bad", ttl_ms=0)
    with pytest.raises(ValueError, match="large"):
        store.put("one", "x" * (1024 * 1024 + 1))


def test_export_requires_authorization_and_defaults_to_metadata(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")
    item = store.put("one", "api_key=secret")
    destination = tmp_path / "export"
    with pytest.raises(PermissionError, match="authorization"):
        store.export("one", destination, [item["id"]])
    assert not destination.exists()

    manifest = store.export("one", destination, [item["id"]], authorized=True)
    assert manifest["includesRaw"] is False
    assert sorted(path.name for path in destination.iterdir()) == ["manifest.json"]
    assert "secret" not in (destination / "manifest.json").read_text()
    assert manifest["artifacts"][0]["sha256"] == item["sha256"]


def test_raw_export_is_scoped_and_verified(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")
    item = store.put("one", "original")
    with pytest.raises(FileNotFoundError):
        store.export("two", tmp_path / "wrong", [item["id"]], authorized=True)
    assert not (tmp_path / "wrong").exists()

    destination = tmp_path / "raw"
    manifest = store.export(
        "one", destination, [item["id"]], authorized=True, include_raw=True
    )
    filename = manifest["artifacts"][0]["file"]
    assert (destination / filename).read_text() == "original"
    assert hashlib.sha256((destination / filename).read_bytes()).hexdigest() == item["sha256"]
    assert destination.stat().st_mode & 0o077 == 0
    assert (destination / filename).stat().st_mode & 0o077 == 0


def test_export_rejects_expired_tampered_and_unsafe_destinations(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")
    item = store.put("one", "short", ttl_ms=1)
    time.sleep(0.005)
    with pytest.raises(ValueError, match="expired"):
        store.export("one", tmp_path / "expired", [item["id"]], authorized=True)
    assert not (tmp_path / "expired").exists()

    item = store.put("one", "safe")
    directory = store.root / hashlib.sha256(b"one").hexdigest()
    (directory / f"{item['id']}.txt").write_text("evil")
    with pytest.raises(ValueError, match="integrity"):
        store.export("one", tmp_path / "tampered", [item["id"]], authorized=True)
    assert not (tmp_path / "tampered").exists()

    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    valid = store.put("one", "valid")
    with pytest.raises(ValueError, match="symlink"):
        store.export("one", tmp_path / "linked", [valid["id"]], authorized=True)
    with pytest.raises(ValueError, match="selection"):
        store.export("one", tmp_path / "empty", [], authorized=True)


def test_export_rejects_parent_symlink_and_traversal(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")
    item = store.put("one", "original")
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        store.export("one", link / "export", [item["id"]], authorized=True)
    assert not (outside / "export").exists()
    with pytest.raises(ValueError, match="traversal"):
        store.export("one", tmp_path / "outside" / ".." / "export", [item["id"]], authorized=True)


def test_failed_export_only_removes_its_own_files(tmp_path: Path, monkeypatch):
    store = ArtifactStore(tmp_path / "artifacts")
    item = store.put("one", "original")
    destination = tmp_path / "export"
    original_open = artifact_module.os.open

    def interrupt_raw_file(path, flags, *args, **kwargs):
        if path == f"{item['id']}.txt":
            (destination / "other.txt").write_text("keep")
            raise OSError("simulated write failure")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(artifact_module.os, "open", interrupt_raw_file)
    with pytest.raises(OSError, match="simulated"):
        store.export(
            "one", destination, [item["id"]], authorized=True, include_raw=True
        )
    assert (destination / "other.txt").read_text() == "keep"
    assert not (destination / "manifest.json").exists()


def test_delete_project_is_scoped_and_idempotent(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")
    one = store.put("one", "secret")
    two = store.put("two", "keep")
    assert store.delete_project("one") == {"removedArtifacts": 1, "leftovers": []}
    assert store.delete_project("one") == {"removedArtifacts": 0, "leftovers": []}
    assert store.get("two", two["id"]) == "keep"
    with pytest.raises(FileNotFoundError):
        store.get("one", one["id"])


def test_delete_project_reports_partial_and_corrupt_files(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")
    good = store.put("one", "good")
    partial = store.put("one", "partial")
    corrupt = store.put("one", "corrupt")
    directory = store.root / hashlib.sha256(b"one").hexdigest()
    (directory / f"{partial['id']}.json").unlink()
    (directory / f"{corrupt['id']}.json").write_text("{}")
    result = store.delete_project("one")
    assert result == {"removedArtifacts": 1, "leftovers": sorted([
        f"{partial['id']}.txt", f"{corrupt['id']}.txt", f"{corrupt['id']}.json"
    ])}
    assert not (directory / f"{good['id']}.txt").exists()
    assert (directory / f"{partial['id']}.txt").exists()
    assert (directory / f"{corrupt['id']}.json").exists()


def test_delete_project_rejects_symlinks_and_unexpected_files(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")
    item = store.put("one", "secret")
    directory = store.root / hashlib.sha256(b"one").hexdigest()
    outside = tmp_path / "outside"
    outside.write_text("keep")
    link = directory / f"{item['id']}.txt"
    link.unlink()
    link.symlink_to(outside)
    with pytest.raises(ValueError, match="Unsafe artifact file"):
        store.delete_project("one")
    assert outside.read_text() == "keep"
    assert (directory / f"{item['id']}.json").exists()
    link.unlink()
    (directory / "unexpected.txt").write_text("unexpected")
    with pytest.raises(ValueError, match="Unexpected artifact file"):
        store.delete_project("one")
    assert (directory / f"{item['id']}.json").exists()


def test_delete_project_rejects_directory_symlink(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")
    outside = tmp_path / "outside"
    outside.mkdir()
    (store.root / hashlib.sha256(b"one").hexdigest()).symlink_to(outside)
    with pytest.raises(ValueError, match="Unsafe artifact directory"):
        store.delete_project("one")


def test_delete_project_leaves_foreign_metadata(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")
    item = store.put("one", "secret")
    directory = store.root / hashlib.sha256(b"one").hexdigest()
    metadata_path = directory / f"{item['id']}.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["projectId"] = "two"
    metadata_path.write_text(json.dumps(metadata))
    result = store.delete_project("one")
    assert result == {"removedArtifacts": 0, "leftovers": sorted([
        f"{item['id']}.txt", f"{item['id']}.json"
    ])}
    assert (directory / f"{item['id']}.txt").exists()
