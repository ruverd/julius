"""External acceptance commands require explicit opt-in and forward limits."""

import json

import pytest

from julius import cli


def test_codex_hook_probe_requires_execute(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(cli, "probe_codex_hook", lambda **kwargs: calls.append(kwargs) or {
        "status": "accepted", "hookInvoked": True, "markerObserved": True, "usage": None,
    })
    with pytest.raises(ValueError, match="requires --execute"):
        cli.run(["probe", "codex-hook"])
    assert calls == []
    assert cli.run(["probe", "codex-hook", "--execute"]) == 0
    assert calls == [{"confirmed": True}]
    assert json.loads(capsys.readouterr().out)["hookInvoked"] is True


def test_codex_hook_probe_reports_failure(monkeypatch, capsys):
    monkeypatch.setattr(cli, "probe_codex_hook", lambda **kwargs: {
        "status": "incomplete", "hookInvoked": False,
        "markerObserved": False, "usage": None,
    })
    assert cli.run(["probe", "codex-hook", "--execute"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "incomplete"


def test_repo_pilot_requires_opt_in_and_limits(monkeypatch, tmp_path, capsys):
    calls = []
    monkeypatch.setattr(cli, "run_repo_task_pilot", lambda **kwargs: calls.append(kwargs) or {
        "conclusion": "exploratory_descriptive_pair_only", "arms": [],
    })
    common = ["evaluate", "repo-pilot", "--project", "pilot", "--work-dir", str(tmp_path)]
    with pytest.raises(ValueError, match="requires --execute"):
        cli.run(common)
    with pytest.raises(ValueError, match="requires --max-budget-usd"):
        cli.run([*common, "--execute"])
    assert calls == []
    assert cli.run([*common, "--execute", "--task", "bug-en", "--model", "haiku",
                    "--max-turns", "2", "--max-budget-usd", "0.02",
                    "--timeout-seconds", "45"]) == 0
    assert calls == [{
        "work_dir": tmp_path, "project_id": "pilot", "max_turns": 2,
        "max_budget_usd": 0.02, "timeout_seconds": 45.0, "model": "haiku",
        "task_ids": ("bug-en",), "claude_executable": "claude",
    }]
    assert json.loads(capsys.readouterr().out)["conclusion"] == "exploratory_descriptive_pair_only"
