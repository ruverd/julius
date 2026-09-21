"""Managed configuration exercises only temporary files."""

import os
from pathlib import Path

import pytest

from julius.managed_config import ManagedConfig


def manager(tmp_path: Path) -> tuple[ManagedConfig, Path]:
    config = tmp_path / "config"
    config.mkdir()
    return ManagedConfig(config, tmp_path / "state"), config


def test_plan_apply_and_restore_exact_original(tmp_path: Path) -> None:
    managed, config = manager(tmp_path)
    target = config / "settings.json"
    original = b'{"setting": 1}\n'
    target.write_bytes(original)
    target.chmod(0o640)
    plan = managed.plan(target, b'{"setting": 2}\n')
    assert target.read_bytes() == original
    assert plan.expected_sha256 is not None
    assert '-{"setting": 1}' in plan.diff
    assert managed.apply(plan)
    assert target.read_bytes() == b'{"setting": 2}\n'
    assert not managed.apply(plan)
    assert managed.remove(target)
    assert target.read_bytes() == original
    assert target.stat().st_mode & 0o777 == 0o640
    assert not managed.remove(target)


def test_new_file_and_drift_refusal(tmp_path: Path) -> None:
    managed, config = manager(tmp_path)
    target = config / "new.json"
    plan = managed.plan(target, b"new")
    assert plan.expected_sha256 is None
    target.write_bytes(b"surprise")
    with pytest.raises(ValueError, match="changed"):
        managed.apply(plan)
    target.unlink()
    assert managed.apply(plan)
    target.write_bytes(b"user edit")
    with pytest.raises(ValueError, match="changed"):
        managed.remove(target)
    assert target.read_bytes() == b"user edit"


def test_new_file_removal_and_private_state(tmp_path: Path) -> None:
    managed, config = manager(tmp_path)
    target = config / "new.json"
    assert managed.apply(managed.plan(target, b"new"))
    assert managed.remove(target)
    assert not target.exists()
    assert not list((tmp_path / "state").iterdir())
    assert os.stat(tmp_path / "state").st_mode & 0o777 == 0o700


def test_rejects_symlinks_and_outside_paths(tmp_path: Path) -> None:
    managed, config = manager(tmp_path)
    outside = tmp_path / "outside"
    outside.write_text("outside")
    (config / "link").symlink_to(outside)
    for target in (outside, config / "link"):
        with pytest.raises(ValueError):
            managed.plan(target, b"new")
    assert outside.read_text() == "outside"


def test_apply_preserves_external_edit_between_backup_and_replace(tmp_path: Path, monkeypatch) -> None:
    import julius.managed_config as module

    managed, config = manager(tmp_path)
    target = config / "settings.json"
    target.write_bytes(b"original")
    plan = managed.plan(target, b"managed")
    write = module._atomic

    def concurrent_write(path, data, mode):
        write(path, data, mode)
        if path.suffix == ".json" and path != target:
            target.write_bytes(b"external edit")

    monkeypatch.setattr(module, "_atomic", concurrent_write)
    with pytest.raises(ValueError, match="changed while applying"):
        managed.apply(plan)
    assert target.read_bytes() == b"external edit"
    assert list((tmp_path / "state").iterdir()) == []
