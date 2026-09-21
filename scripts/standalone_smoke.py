"""Offline smoke for a built Julius standalone executable."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


def _run(binary: Path, *args: str, data_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(binary), *args, "--data-dir", str(data_dir)],
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/standalone_smoke.py PATH_TO_JULIUS")
    binary = Path(sys.argv[1]).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="julius-standalone-smoke-") as directory:
        data_dir = Path(directory)
        version = _run(binary, "--version", data_dir=data_dir).stdout.strip()
        if not version.startswith("julius-local "):
            raise AssertionError(f"Unexpected version: {version!r}")
        module_version = _run(binary, "-m", "julius.cli", "--version", data_dir=data_dir)
        if module_version.stdout.strip() != version:
            raise AssertionError("Bundled module dispatch differs from CLI version")
        doctor = json.loads(_run(binary, "doctor", "--json", data_dir=data_dir).stdout)
        evidence = doctor["localProtocolProbe"]["evidence"]
        if not all(evidence[key] for key in (
            "hook_candidate", "mcp_initialize", "mcp_tools_list", "artifact_restore",
        )):
            raise AssertionError(f"Bundled hook/MCP probe failed: {doctor['localProtocolProbe']}")
        if list(data_dir.glob("*.sqlite")):
            raise AssertionError("Doctor left ledger files in smoke directory")
    print(f"Standalone smoke passed: {version}; hook/MCP recovery protocol")


if __name__ == "__main__":
    main()
