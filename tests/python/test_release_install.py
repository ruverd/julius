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
