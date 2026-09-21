"""Project-scoped retention commands keep independent local stores distinct."""

import hashlib
import json
import os
from contextlib import closing
from pathlib import Path
import subprocess
import sys

from julius.artifacts import ArtifactStore
from julius.ledger import Ledger


def _run(data_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "julius", *args, "--data-dir", str(data_dir)],
        text=True, capture_output=True, timeout=10,
        env={**os.environ, "JULIUS_HOME": str(data_dir)},
    )


def _usage(project: str, name: str, occurred_at: str) -> dict:
    return {
        "schemaVersion": 1, "eventId": name, "occurredAt": occurred_at,
        "sourceId": "fixture", "sourceEventId": name, "projectId": project,
        "taskId": None, "sessionId": name, "requestId": name,
        "attemptId": name, "clientId": "test", "adapterVersion": "1",
        "modelId": None, "providerId": None, "executionLocation": "unknown",
        "eventType": "usage", "evidence": "heuristic_estimate",
        "payload": {"inputTokens": 10, "outputTokens": 5,
                    "cacheReadTokens": None, "cacheWriteTokens": None,
                    "complete": True, "category": "primary", "callId": name,
                    "costUsd": None, "observationScope": "call"},
    }


def test_cli_events_purge_then_delete_project_preserves_other_project(tmp_path: Path):
    data_dir = tmp_path / "data"
    with closing(Ledger(data_dir / "ledger.sqlite")) as ledger:
        ledger.record(_usage("one", "old", "2026-09-20T00:00:00.000Z"))
        ledger.record(_usage("one", "new", "2026-09-21T00:00:00.000Z"))
        ledger.record(_usage("other", "foreign", "2026-09-20T00:00:00.000Z"))

    missing = _run(data_dir, "events", "purge", "--project", "one")
    assert missing.returncode == 1
    invalid = _run(data_dir, "events", "purge", "--project", "one", "--before", "2026-09-21")
    assert invalid.returncode == 1
    purged = _run(data_dir, "events", "purge", "--project", "one",
                  "--before", "2026-09-21T00:00:00Z")
    assert purged.returncode == 0, purged.stderr
    assert json.loads(purged.stdout) == {
        "removedEvents": 1, "removedAliases": 0, "retainedByDependency": 0,
    }
    with closing(Ledger(data_dir / "ledger.sqlite")) as ledger:
        assert {event["eventId"] for event in ledger.history()} == {"new", "foreign"}

    deleted = _run(data_dir, "events", "delete-project", "--project", "one")
    assert deleted.returncode == 0, deleted.stderr
    assert json.loads(deleted.stdout) == {"removedEvents": 1, "removedAliases": 0}
    with closing(Ledger(data_dir / "ledger.sqlite")) as ledger:
        assert [event["eventId"] for event in ledger.history()] == ["foreign"]


def test_cli_artifact_project_delete_reports_leftovers_and_keeps_foreign(tmp_path: Path):
    data_dir = tmp_path / "data"
    store = ArtifactStore(data_dir / "artifacts")
    good = store.put("one", "delete me")
    partial = store.put("one", "cannot attribute")
    foreign = store.put("other", "keep")
    directory = store.root / hashlib.sha256(b"one").hexdigest()
    (directory / f"{partial['id']}.json").unlink()

    result = _run(data_dir, "artifacts", "delete-project", "--project", "one")
    assert result.returncode == 2, result.stderr
    assert json.loads(result.stdout) == {
        "removedArtifacts": 1, "leftovers": [f"{partial['id']}.txt"],
    }
    assert not (directory / f"{good['id']}.txt").exists()
    assert store.get("other", foreign["id"]) == "keep"
