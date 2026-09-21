import json

import pytest

import julius.cli as cli


def test_claude_runner_requires_recovery_for_safe_profile(tmp_path, monkeypatch):
    calls = []

    def launch(**arguments):
        calls.append(arguments)
        return 0

    monkeypatch.setattr(cli, "run_claude", launch)
    common = ["run", "--agent", "claude", "--project", "p", "--data-dir", str(tmp_path)]
    assert cli.run(common) == 0
    assert calls[0]["enable_safe_hook"] is False
    with pytest.raises(ValueError, match="requires --recovery-verified"):
        cli.run([*common, "--profile", "safe"])
    assert cli.run([*common, "--profile", "safe", "--recovery-verified"]) == 0
    assert calls[1]["enable_safe_hook"] is True
    assert calls[1]["recovery_verified"] is True
    with pytest.raises(ValueError, match="task attribution"):
        cli.run([*common, "--task", "DEV-123"])


def test_lmstudio_model_selection_is_explicit(monkeypatch, capsys):
    monkeypatch.setattr(cli, "discover_lmstudio", lambda endpoint: {
        "endpoint": endpoint, "models": [], "error": None,
    })
    assert cli.run(["models", "list", "--runtime", "lmstudio"]) == 0
    assert json.loads(capsys.readouterr().out)["endpoint"] == "http://127.0.0.1:1234"
