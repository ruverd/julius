import json
import os
import subprocess
import sys
from pathlib import Path

from julius.sdk import Julius

FIXTURE = Path(__file__).parents[1] / "fixtures" / "events.jsonl"


def test_cli_lifecycle(tmp_path):
    def run(*args, success=True):
        process = subprocess.run(
            [sys.executable, "-m", "julius", *args],
            capture_output=True,
            text=True,
            env={**os.environ, "JULIUS_HOME": str(tmp_path / "data")},
        )
        assert (process.returncode == 0) == success, process.stderr
        return process.stdout

    assert "0.2.0" in run("--version")
    assert json.loads(run("import", str(FIXTURE)))["imported"] == 3
    assert json.loads(run("import", str(FIXTURE)))["duplicates"] == 3
    window = ("--since", "2026-09-21T00:00:00Z", "--until", "2026-09-22T00:00:00Z")
    report = json.loads(run("savings", *window, "--json"))
    assert report["directInputReduction"][0]["tokens"]["total"] == 7000
    assert report["financialSavingsUsd"] is None
    log = tmp_path / "output.txt"
    original = ("neutral status text " + "x" * 240 + "\n") * 4
    log.write_text(original)
    optimized = json.loads(run("optimize", str(log), "--project", "p", "--profile", "safe"))
    assert optimized["receipt"]["applied"] is True
    artifact = optimized["original"]["id"]
    assert run("restore", artifact, "--project", "p") == original
    metadata_export = tmp_path / "metadata-export"
    manifest = json.loads(run("artifacts", "export", artifact, "--project", "p",
                              "--output", str(metadata_export)))
    assert manifest["includesRaw"] is False
    assert sorted(path.name for path in metadata_export.iterdir()) == ["manifest.json"]
    raw_export = tmp_path / "raw-export"
    raw_manifest = json.loads(run("artifacts", "export", artifact, "--project", "p",
                                  "--output", str(raw_export), "--include-originals"))
    assert raw_manifest["includesRaw"] is True
    assert (raw_export / f"{artifact}.txt").read_text() == original
    run("artifacts", "export", artifact, "--project", "other",
        "--output", str(tmp_path / "cross-project"), success=False)
    assert not (tmp_path / "cross-project").exists()
    run("restore", artifact, "--project", "other", success=False)
    run("artifacts", "delete", artifact, "--project", "p")
    run("restore", artifact, "--project", "p", success=False)
    target = tmp_path / "report.html"
    run("dashboard", *window, "--output", str(target))
    assert target.read_text().startswith("<!doctype html>")
    assert "id='filter-model'" in target.read_text()
    assert '"group"' in run("export", *window, "--format", "csv")
    run("run", success=False)


def test_observe_and_denied_requests_do_not_store_content(tmp_path):
    with Julius(tmp_path) as julius:
        context = {"projectId": "p", "content": "private", "category": "tool_output"}
        assert julius.optimize(context, {"mode": "observe", "version": "1.0.0"})["original"] is None
        assert (
            julius.optimize(context, {"mode": "safe", "version": "1.0.0", "approved": False})[
                "original"
            ]
            is None
        )
        assert list((tmp_path / "artifacts").iterdir()) == []


def test_native_failure_does_not_leave_original_content(tmp_path, monkeypatch):
    import julius.sdk as sdk

    import pytest

    calls = 0

    def failing_optimizer(context, policy):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"candidate": context["content"], "receipt": {"reason": "recovery_required"}}
        raise RuntimeError("native failure")

    monkeypatch.setattr(sdk, "optimize", failing_optimizer)
    with Julius(tmp_path) as julius:
        with pytest.raises(RuntimeError, match="native failure"):
            julius.optimize({"projectId": "p", "content": "private"}, {"mode": "safe"})
        assert list((tmp_path / "artifacts").rglob("*.txt")) == []
