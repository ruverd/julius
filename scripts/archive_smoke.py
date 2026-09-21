"""Preview, install, launch, and remove one local standalone archive."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

from install_standalone import load_archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    archive = args.archive.resolve(strict=True)
    manifest, _ = load_archive(archive)
    installer = Path(__file__).with_name("install_standalone.py")
    with tempfile.TemporaryDirectory(prefix="julius-archive-smoke-") as directory:
        prefix = Path(directory).resolve() / "managed"

        def install(action: str, *, apply: bool) -> str:
            command = [sys.executable, str(installer), action, "--prefix", str(prefix)]
            if action == "install":
                command.extend(("--archive", str(archive)))
            if apply:
                command.append("--apply")
            return subprocess.run(command, check=True, capture_output=True, text=True,
                                  timeout=30).stdout.strip()

        if not install("install", apply=False).startswith("Preview: ") or prefix.exists():
            raise AssertionError("Install preview changed managed files")
        if not install("install", apply=True).startswith("Applied: "):
            raise AssertionError("Archive installation was not applied")
        result = subprocess.run([str(prefix / "bin" / "julius"), "--version"],
                                check=True, capture_output=True, text=True, timeout=30)
        expected = f"julius-local {manifest['version']} (Python + Rust)"
        if result.stdout.strip() != expected:
            raise AssertionError(f"Installed version mismatch: {result.stdout.strip()!r}")
        if not install("remove", apply=False).startswith("Preview: "):
            raise AssertionError("Removal preview failed")
        if not install("remove", apply=True).startswith("Applied: "):
            raise AssertionError("Managed removal failed")
        if (prefix / "bin" / "julius").exists() or (prefix / ".julius-install.json").exists():
            raise AssertionError("Managed removal left executable or state")
        if "no changes" not in install("remove", apply=True):
            raise AssertionError("Repeated removal was not idempotent")
    print(f"Archive smoke passed: {archive.name}; {expected}; preview/install/remove")


if __name__ == "__main__":
    main()
