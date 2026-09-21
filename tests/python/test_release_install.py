"""Release archive and managed installation lifecycle."""

import importlib.util
import io
import json
from pathlib import Path
import platform
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = load("install_standalone")
packager = load("package_standalone")


def archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str, content: bytes) -> Path:
    binary = tmp_path / f"binary-{version}"
    binary.write_bytes(content)
    binary.chmod(0o755)
    output = tmp_path / f"julius-{version}.tar.gz"
    monkeypatch.setattr("sys.argv", ["package", "--binary", str(binary), "--output", str(output), "--version", version])
    packager.main()
    return output


def test_install_update_rollback_remove(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = archive(tmp_path, monkeypatch, "0.2.0", b"first")
    second = archive(tmp_path, monkeypatch, "0.3.0", b"second")
    prefix = tmp_path / "prefix"
    binary = prefix / "bin" / "julius"
    assert "Preview" in installer.execute("install", prefix, first, False)
    assert not prefix.exists()
    installer.execute("install", prefix, first, True)
    assert binary.read_bytes() == b"first"
    assert "no changes" in installer.execute("update", prefix, first, True)
    installer.execute("update", prefix, second, True)
    assert binary.read_bytes() == b"second"
    assert (prefix / ".julius-backups" / installer.digest(b"first")).read_bytes() == b"first"
    installer.execute("rollback", prefix, None, True)
    assert binary.read_bytes() == b"first"
    assert "no changes" in installer.execute("rollback", prefix, None, True)
    installer.execute("remove", prefix, None, True)
    assert not binary.exists()
    assert "no changes" in installer.execute("remove", prefix, None, True)


def test_refuses_unmanaged_and_modified_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    release = archive(tmp_path, monkeypatch, "0.2.0", b"first")
    prefix = tmp_path / "prefix"
    (prefix / "bin").mkdir(parents=True)
    binary = prefix / "bin" / "julius"
    binary.write_bytes(b"unrelated")
    with pytest.raises(ValueError, match="unmanaged"):
        installer.execute("install", prefix, release, True)
    binary.unlink()
    binary.symlink_to(tmp_path / "target")
    with pytest.raises(ValueError, match="symlink"):
        installer.execute("install", prefix, release, True)
    binary.unlink()
    installer.execute("install", prefix, release, True)
    binary.write_bytes(b"changed")
    with pytest.raises(ValueError, match="modified"):
        installer.execute("remove", prefix, None, True)


def test_archive_manifest_and_platform_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    release = archive(tmp_path, monkeypatch, "0.2.0", b"first")
    with tarfile.open(release, "r:gz") as bundle:
        manifest = json.load(bundle.extractfile("manifest.json"))
    assert manifest["platform"] == platform.system().lower()
    assert manifest["architecture"] == platform.machine().lower()
    assert manifest["files"]["julius"] == installer.digest(b"first")
    monkeypatch.setattr(installer.platform, "machine", lambda: "wrong-architecture")
    with pytest.raises(ValueError, match="platform or architecture"):
        installer.execute("install", tmp_path / "prefix", release, False)


def test_duplicate_archive_member_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    release = archive(tmp_path, monkeypatch, "0.2.0", b"first")
    duplicate = tmp_path / "duplicate.tar.gz"
    with tarfile.open(release, "r:gz") as source, tarfile.open(duplicate, "w:gz") as target:
        for member in source.getmembers():
            content = source.extractfile(member).read()
            target.addfile(member, io.BytesIO(content))
            if member.name == "manifest.json":
                target.addfile(member, io.BytesIO(content))
    with pytest.raises(ValueError, match="unexpected archive contents"):
        installer.load_archive(duplicate)


def test_recovers_after_binary_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = archive(tmp_path, monkeypatch, "0.2.0", b"first")
    second = archive(tmp_path, monkeypatch, "0.3.0", b"second")
    prefix = tmp_path / "prefix"
    installer.execute("install", prefix, first, True)
    original = installer.write_atomic

    def fail_state(path: Path, data: bytes, mode: int) -> None:
        if path.name == installer.STATE_NAME:
            raise OSError("simulated crash")
        original(path, data, mode)

    monkeypatch.setattr(installer, "write_atomic", fail_state)
    with pytest.raises(OSError, match="simulated crash"):
        installer.execute("update", prefix, second, True)
    monkeypatch.setattr(installer, "write_atomic", original)
    assert "recover interrupted update" in installer.execute("rollback", prefix, None, False)
    assert "Recovered" in installer.execute("rollback", prefix, None, True)
    assert (prefix / "bin" / "julius").read_bytes() == b"second"
    assert json.loads((prefix / installer.STATE_NAME).read_text())["current"]["version"] == "0.3.0"
    installer.execute("rollback", prefix, None, True)
    assert (prefix / "bin" / "julius").read_bytes() == b"first"


def test_rejects_symlink_parent_and_invalid_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    release = archive(tmp_path, monkeypatch, "0.2.0", b"first")
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink in prefix path"):
        installer.execute("install", link / "nested", release, True)
    installer.execute("install", real, release, True)
    state_path = real / installer.STATE_NAME
    state = json.loads(state_path.read_text())
    state["history"] = ["invalid"]
    state_path.write_text(json.dumps(state))
    with pytest.raises(ValueError, match="invalid managed state"):
        installer.execute("remove", real, None, True)
    assert (real / "bin" / "julius").read_bytes() == b"first"


def test_recovers_interrupted_removal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    release = archive(tmp_path, monkeypatch, "0.2.0", b"first")
    prefix = tmp_path / "prefix"
    installer.execute("install", prefix, release, True)
    original = installer.Path.unlink

    def fail_state_unlink(path: Path, *args, **kwargs) -> None:
        if path.name == installer.STATE_NAME:
            raise OSError("simulated crash")
        original(path, *args, **kwargs)

    monkeypatch.setattr(installer.Path, "unlink", fail_state_unlink)
    with pytest.raises(OSError, match="simulated crash"):
        installer.execute("remove", prefix, None, True)
    monkeypatch.setattr(installer.Path, "unlink", original)
    assert "recover interrupted remove" in installer.execute("remove", prefix, None, False)
    assert "Recovered" in installer.execute("remove", prefix, None, True)
    assert not (prefix / "bin" / "julius").exists()
    assert not (prefix / installer.STATE_NAME).exists()
    assert not (prefix / installer.BACKUP_NAME).exists()
