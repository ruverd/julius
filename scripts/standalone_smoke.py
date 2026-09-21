"""Offline smoke for a built Julius standalone executable."""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timedelta, timezone
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
        captures = data_dir / "jev-captures.json"
        captures.write_text('{"captures":[]}', encoding="utf-8")
        jev_replay = json.loads(_run(
            binary, "evaluate", "jev-shadow", "--state-file", str(captures),
            data_dir=data_dir,
        ).stdout)
        if (jev_replay["planned_cases"] != 6 or jev_replay["captured_cases"] != 0
                or jev_replay["auxiliary_cost_usd"] is not None):
            raise AssertionError("Bundled Jev registration or unknown totals are invalid")
        codex_hook = subprocess.run(
            [str(binary), "hook", "codex-user-prompt-submit"],
            input=json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "smoke",
                              "cwd": str(data_dir), "prompt": "synthetic"}),
            capture_output=True, text=True, check=True, timeout=30,
        )
        if codex_hook.stdout != "{}\n" or codex_hook.stderr:
            raise AssertionError("Bundled Codex hook default was not an offline no-op")
        now = datetime.now(timezone.utc)
        content = "standalone memory fixture"
        record = {
            "id": "smoke", "version": 1, "projectId": "smoke", "snapshot": "snapshot-a",
            "content": content, "contentSha256": hashlib.sha256(content.encode()).hexdigest(),
            "createdAt": (now - timedelta(seconds=1)).isoformat(timespec="microseconds").replace(
                "+00:00", "Z"
            ),
            "expiresAt": (now + timedelta(minutes=1)).isoformat(timespec="microseconds").replace(
                "+00:00", "Z"
            ),
            "provenance": "observed", "origin": "standalone-smoke",
        }
        record_path = data_dir / "record.json"
        record_path.write_text(json.dumps(record))
        _run(binary, "memory", "put", str(record_path), "--project", "smoke", data_dir=data_dir)
        hits = json.loads(_run(
            binary, "memory", "search", "standalone", "--project", "smoke",
            "--snapshot", "snapshot-a", data_dir=data_dir,
        ).stdout)
        if len(hits) != 1 or hits[0]["contentSha256"] != record["contentSha256"]:
            raise AssertionError("Bundled memory search did not restore its indexed evidence")
        _run(binary, "memory", "invalidate", "smoke", "--project", "smoke",
             "--invalidation-reason", "smoke_complete", data_dir=data_dir)
        history = json.loads(_run(
            binary, "memory", "history", "smoke", "--project", "smoke",
            data_dir=data_dir,
        ).stdout)
        if (len(history["records"]) != 1 or not history["records"][0]["invalidated"]
                or history["records"][0]["invalidationReason"] != "smoke_complete"
                or "content" in history["records"][0]):
            raise AssertionError("Bundled memory history lost invalidation audit or exposed content")
    print(f"Standalone smoke passed: {version}; hook/MCP recovery, Codex hook, Jev replay, and memory search")


if __name__ == "__main__":
    main()
