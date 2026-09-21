import json

import pytest

from julius import cli


def test_pilot_cli_requires_explicit_execution_before_any_client_call(monkeypatch, tmp_path):
    def forbidden(**kwargs):
        raise AssertionError("client called")

    monkeypatch.setattr(cli, "run_claude_pilot", forbidden)
    with pytest.raises(ValueError, match="requires --execute"):
        cli.run(["evaluate", "pilot", "--project", "p", "--work-dir", str(tmp_path),
                 "--order-seed", "7", "--max-budget-usd", "0.02",
                 "--timeout-seconds", "30"])


def test_pilot_cli_passes_explicit_limits_and_prints_report(monkeypatch, tmp_path, capsys):
    observed = []

    def fake_pilot(**kwargs):
        observed.append(kwargs)
        return {"conclusion": "descriptive_pilot_only", "attempts": []}

    monkeypatch.setattr(cli, "run_claude_pilot", fake_pilot)
    assert cli.run(["evaluate", "pilot", "--execute", "--project", "p",
                    "--work-dir", str(tmp_path), "--order-seed", "7",
                    "--max-turns", "3", "--max-budget-usd", "0.02",
                    "--timeout-seconds", "30", "--model", "haiku"]) == 0
    assert observed == [{"work_dir": tmp_path, "project_id": "p", "max_turns": 3,
                         "max_budget_usd": 0.02, "timeout_seconds": 30.0,
                         "order_seed": 7, "model": "haiku",
                         "claude_executable": "claude"}]
    assert json.loads(capsys.readouterr().out)["conclusion"] == "descriptive_pilot_only"


def test_pilot_report_cli_analyzes_local_file_without_client(monkeypatch, tmp_path, capsys):
    source = tmp_path / "report.json"
    source.write_text('{"complete":true}', encoding="utf-8")
    observed = []

    def fake_analyze(payload):
        observed.append(payload)
        return {"interpretation": "descriptive_only"}

    def forbidden(**kwargs):
        raise AssertionError("client called")

    monkeypatch.setattr(cli, "analyze_claude_pilot_report", fake_analyze)
    monkeypatch.setattr(cli, "run_claude_pilot", forbidden)
    assert cli.run(["evaluate", "pilot-report", "--state-file", str(source)]) == 0
    assert observed == [{"complete": True}]
    assert json.loads(capsys.readouterr().out) == {"interpretation": "descriptive_only"}
