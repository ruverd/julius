"""Frozen outputs from the verified TypeScript checkpoint, commit 3616024."""

import json
from pathlib import Path

from julius.optimizer import optimize
from julius.reporting import report

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_native_optimizer_matches_frozen_reference_contract():
    inputs = json.loads((FIXTURES / "optimization.json").read_text())
    expected = json.loads((FIXTURES / "optimization.expected.json").read_text())
    for item, reference in zip(inputs, expected, strict=True):
        result = optimize(
            {
                "projectId": "parity",
                "category": "tool_output",
                "content": item["content"],
                "recovery": {
                    "artifactId": "11111111-1111-1111-1111-111111111111",
                    "available": True,
                },
            },
            {"mode": "safe", "version": "1.0.0", "approved": True},
        )
        assert result == reference["result"], item["name"]


def test_report_matches_frozen_reference_contract():
    expected = json.loads((FIXTURES / "report.expected.json").read_text())
    events = [json.loads(line) for line in (FIXTURES / "events.jsonl").read_text().splitlines()]
    window = {
        "since": "2026-09-21T00:00:00.000Z",
        "until": "2026-09-22T00:00:00.000Z",
        "timezone": "UTC",
    }
    assert report(events, window) == expected
