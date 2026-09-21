import json

import pytest

import julius.cli as cli


def test_xai_modes_dispatch_explicitly_without_extra_send(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XAI_API_KEY", "fixture-key")
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps({"model": "grok-fixture", "input": "Hi"}))
    observed = []

    def fake_send(self, request, **kwargs):
        observed.append((request, kwargs))
        return {"complete": True, "attempts": [], "mode": kwargs.get("policy", {}).get("mode", "observe")}

    monkeypatch.setattr("julius.sdk.Julius.send_xai_optimized", fake_send)
    monkeypatch.setattr("julius.sdk.Julius.send_xai_with_restores", fake_send)
    common = ["run", "--agent", "grok", "--request", str(request_file),
              "--project", "project", "--data-dir", str(tmp_path / "data")]
    assert cli.run([*common, "--profile", "safe", "--max-restore-calls", "2"]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "safe"
    assert observed[0][1]["max_calls"] == 2
    assert cli.run([*common, "--restore-loop"]) == 0
    assert observed[1][1]["max_calls"] == 4
    assert len(observed) == 2
    with pytest.raises(ValueError, match="already includes"):
        cli.run([*common, "--profile", "safe", "--restore-loop"])
    assert len(observed) == 2
