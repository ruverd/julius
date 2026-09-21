"""CLI evaluates frozen Jev captures entirely offline."""

import json

import pytest

from julius.cli import run


def test_empty_shadow_replay_keeps_unknown_cost(tmp_path, capsys):
    path = tmp_path / "captures.json"
    path.write_text('{"captures":[]}', encoding="utf-8")
    assert run(["evaluate", "jev-shadow", "--state-file", str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["planned_cases"] == 6
    assert report["captured_cases"] == 0
    assert report["accuracy"] is None
    assert report["auxiliary_cost_usd"] is None


def test_shadow_replay_rejects_unknown_case(tmp_path):
    path = tmp_path / "captures.json"
    path.write_text(json.dumps({"captures": [{
        "case_id": "unknown", "choice": "keep", "confidence": 0.5,
    }]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Unregistered case"):
        run(["evaluate", "jev-shadow", "--state-file", str(path)])
