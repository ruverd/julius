"""Black-box acceptance for the local stdio boundary proposed for Bulma."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[2]
WINDOW = {"since": "2026-09-21T00:00:00.000Z", "until": "2026-09-22T00:00:00.000Z"}


def request(request_id: str, operation: str, params: dict) -> dict:
    return {"protocolVersion": 1, "id": request_id, "operation": operation, "params": params}


def exchange(store: Path, lines: list[str]) -> list[dict]:
    env = os.environ.copy()
    guard = store.parent / "network-guard"
    guard.mkdir(exist_ok=True)
    (guard / "sitecustomize.py").write_text(
        "import socket\n"
        "def deny(self, address):\n"
        f"    open({str(guard / 'attempted-network')!r}, 'a').write(repr(address) + '\\n')\n"
        "    raise AssertionError('stdio attempted a network connection')\n"
        "socket.socket.connect = deny\n"
        "socket.socket.connect_ex = deny\n"
    )
    env["PYTHONPATH"] = os.pathsep.join((str(guard), str(ROOT / "python")))
    for name in tuple(env):
        if name.endswith("_API_KEY") or name.endswith("_TOKEN"):
            env.pop(name)
    completed = subprocess.run(
        [sys.executable, "-m", "julius", "serve", "--data-dir", str(store)],
        input="\n".join(lines) + "\n", text=True, capture_output=True,
        env=env, cwd=ROOT, timeout=15, check=True,
    )
    assert completed.stderr == ""
    assert not (guard / "attempted-network").exists()
    responses = [json.loads(line) for line in completed.stdout.splitlines()]
    assert len(responses) == len(lines)
    return responses


def event(event_id: str, source_event_id: str, attempt: str, call: str) -> dict:
    return {
        "schemaVersion": 1, "eventId": event_id,
        "occurredAt": "2026-09-21T12:00:00.000Z", "sourceId": "bulma-stdio-test",
        "sourceEventId": source_event_id, "projectId": "synthetic-project",
        "taskId": "synthetic-task", "sessionId": "synthetic-session",
        "requestId": "synthetic-request", "attemptId": attempt,
        "clientId": "synthetic-client", "adapterVersion": "1.0.0",
        "modelId": "synthetic-model", "providerId": None,
        "executionLocation": "unknown", "evidence": "runtime_reported",
        "eventType": "usage",
        "payload": {"inputTokens": 10, "outputTokens": 2,
                    "cacheReadTokens": None, "cacheWriteTokens": None,
                    "complete": True, "category": "primary", "callId": call,
                    "costUsd": None},
    }


def test_stdio_persists_one_ledger_and_counts_distinct_attempts(tmp_path: Path) -> None:
    store = tmp_path / "store"
    first = event("usage-1", "source-1", "attempt-1", "call-1")
    retry = event("usage-2", "source-2", "attempt-2", "call-2")
    outcome = {**first, "eventId": "outcome-1", "sourceEventId": "outcome-1",
               "eventType": "outcome", "payload": {"outcome": "success", "reason": None}}
    requests = [
        request("usage:first", "recordUsage", {"event": first}),
        request("usage:duplicate", "recordUsage", {"event": first}),
        request("usage:retry", "recordUsage", {"event": retry}),
        request("outcome", "recordOutcome", {"event": outcome}),
        request("report:before", "report", {"query": WINDOW}),
    ]
    responses = exchange(store, [json.dumps(item) for item in requests])
    assert [item["id"] for item in responses] == [item["id"] for item in requests]
    assert all(item["protocolVersion"] == 1 and item["ok"] for item in responses)
    assert [item["result"]["inserted"] for item in responses[:4]] == [True, False, True, True]
    assert responses[1]["result"]["duplicateOf"] == "usage-1"
    before = responses[4]["result"]
    assert before["observedCalls"] == 2
    assert before["usageRecords"] == 2
    assert before["financialSavingsUsd"] is None

    restarted = exchange(store, [json.dumps(request("report:after", "report", {"query": WINDOW}))])
    assert restarted[0]["id"] == "report:after"
    assert restarted[0]["ok"]
    assert restarted[0]["result"] == before
    with sqlite3.connect(store / "ledger.sqlite") as database:
        assert database.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 3
        assert database.execute("SELECT COUNT(*) FROM events WHERE event_type='usage'").fetchone()[0] == 2
        assert database.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert sorted(path.name for path in store.glob("*.sqlite")) == ["ledger.sqlite"]


def test_stdio_malformed_line_recovers_and_keeps_request_ids(tmp_path: Path) -> None:
    valid = request("report:valid", "report", {"query": WINDOW})
    wrong_version = request("version:bad", "report", {"query": WINDOW})
    wrong_version["protocolVersion"] = 2
    responses = exchange(tmp_path / "store", [
        "{broken", json.dumps(wrong_version),
        json.dumps({**valid, "id": ""}), json.dumps(valid),
    ])
    assert [(item["id"], item["ok"]) for item in responses] == [
        (None, False), ("version:bad", False), (None, False), ("report:valid", True),
    ]
    assert [item["error"] for item in responses[:3]] == [
        "invalid_json", "unsupported_protocol_version", "invalid_id",
    ]
