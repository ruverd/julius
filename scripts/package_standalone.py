"""Package a locally built Julius executable for one target platform."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import tarfile


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=Path("dist/standalone/julius"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    if not args.version or any(c not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-_" for c in args.version):
        parser.error("version must use letters, digits, dot, dash, or underscore")
    if args.binary.is_symlink() or not args.binary.is_file() or not os.access(args.binary, os.X_OK):
        parser.error("binary must be a regular executable, not a symlink")
    binary = args.binary.read_bytes()
    installer = Path(__file__).with_name("install_standalone.py").read_bytes()
    system = platform.system().lower()
    machine = platform.machine().lower()
    manifest = {
        "schema": 1,
        "product": "julius",
        "version": args.version,
        "platform": system,
        "architecture": machine,
        "files": {
            "julius": sha256(binary),
            "install_standalone.py": sha256(installer),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.output, "w:gz") as archive:
        for name, data, mode in (
            ("manifest.json", (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(), 0o644),
            ("julius", binary, 0o755),
            ("install_standalone.py", installer, 0o755),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = mode
            archive.addfile(info, io.BytesIO(data))
    print(f"Created {args.output}: {system}/{machine}, version {args.version}, binary SHA-256 {manifest['files']['julius']}")


if __name__ == "__main__":
    main()
