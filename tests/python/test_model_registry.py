import sqlite3
import stat

import pytest
from pydantic import ValidationError

from julius.model_registry import ModelRegistry, ModelSnapshot


def snapshot(endpoint="http://127.0.0.1:11434", **changes):
    fields = {"endpoint": endpoint, "provider": "ollama", "requested_model": "alias:latest",
              "source": "ollama-tags"}
    fields.update(changes)
    return ModelSnapshot(**fields)


def test_endpoint_sensitive_history_and_unknowns_survive_reopen(tmp_path):
    path = tmp_path / "models.sqlite"
    with ModelRegistry(path) as registry:
        unknown = registry.add(snapshot())
        installed = registry.add(snapshot(state="installed", responded_model="model:7b",
                                          digest="sha256:abc", quantization="Q4_K_M",
                                          tokenizer="tok-v1", template="chatml",
                                          context_window=8192,
                                          tool_capabilities={"function_calling": None}))
        other = registry.add(snapshot("http://127.0.0.1:1234", state="loaded"))
        assert unknown["state"] == "unknown"
        assert unknown["context_window"] is None
        assert unknown["tool_capabilities"] == {}
        assert unknown["identityId"] != installed["identityId"]
        assert unknown["identityId"] != other["identityId"]
        assert len(registry.history(endpoint=unknown["endpoint"], requested_model="alias:latest")) == 2
        assert registry.latest(endpoint=unknown["endpoint"], requested_model="alias:latest") == installed
    with ModelRegistry(path) as registry:
        assert registry.history(endpoint=unknown["endpoint"], requested_model="alias:latest") == [unknown, installed]
        assert registry.latest(endpoint=other["endpoint"], requested_model="alias:latest") == other


def test_history_is_immutable_even_to_direct_sql(tmp_path):
    with ModelRegistry(tmp_path / "models.sqlite") as registry:
        item = registry.add(snapshot())
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            registry.db.execute("UPDATE model_snapshots SET body='{}' WHERE snapshot_id=?",
                                (item["snapshotId"],))
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            registry.db.execute("DELETE FROM model_snapshots WHERE snapshot_id=?",
                                (item["snapshotId"],))


def test_runtime_schema_rejects_fabricated_zero_and_naive_time():
    with pytest.raises(ValidationError):
        snapshot(context_window=0)
    with pytest.raises(ValidationError):
        snapshot(tool_capabilities={"functions": "yes"})
    with pytest.raises(ValidationError):
        snapshot(source_updated_at="2026-09-21T00:00:00Z")
    with pytest.raises(ValidationError):
        snapshot(state="possibly_installed")


def test_registry_file_is_private_and_existing_unsafe_file_is_preserved(tmp_path):
    path = tmp_path / "models.sqlite"
    with ModelRegistry(path) as registry:
        registry.add(snapshot())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    path.chmod(0o644)
    with pytest.raises(ValueError, match="unsafe permissions"):
        ModelRegistry(path)
    assert path.stat().st_size > 0


def test_registry_rejects_symlink(tmp_path):
    actual = tmp_path / "actual.sqlite"
    with ModelRegistry(actual):
        pass
    link = tmp_path / "linked.sqlite"
    link.symlink_to(actual)
    with pytest.raises(ValueError, match="symlink"):
        ModelRegistry(link)
