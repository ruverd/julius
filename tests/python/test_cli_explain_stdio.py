"""Public CLI paths for offline task explanations and versioned stdio."""

import io
import json
from pathlib import Path

from julius.cli import run
from julius.sdk import Julius

FIXTURE = Path(__file__).parents[1] / "fixtures" / "events.jsonl"


def test_task_explanation_preserves_unknown_baseline(tmp_path: Path, capsys) -> None:
    store = tmp_path / "store"
    events = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    with Julius(store) as julius:
        julius.ledger.record_many(events)
    assert run([
        "savings", "--task", "DEMO-1", "--explain", "--json",
        "--since", "2026-09-21T00:00:00Z", "--until", "2026-09-22T00:00:00Z",
        "--data-dir", str(store),
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["observedInputTokens"] is None
    assert result["baselineId"] is None
    assert result["netModeledSavingsUsd"] is None
    assert result["coverageComplete"] is False


def test_cli_serve_processes_offline_jsonl(tmp_path: Path, monkeypatch) -> None:
    request = {"protocolVersion": 1, "id": "report-1", "operation": "report", "params": {"query": {}}}
    input_stream = io.StringIO(json.dumps(request) + "\n")
    output_stream = io.StringIO()
    monkeypatch.setattr("sys.stdin", input_stream)
    monkeypatch.setattr("sys.stdout", output_stream)
    assert run(["serve", "--data-dir", str(tmp_path / "store")]) == 0
    response = json.loads(output_stream.getvalue())
    assert response["ok"] is True
    assert response["id"] == "report-1"
    assert response["result"]["financialSavingsUsd"] is None
