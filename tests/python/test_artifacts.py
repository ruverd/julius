from pathlib import Path
import hashlib
import json
import time

import pytest

from julius.artifacts import ArtifactStore


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
