"""Frozen outputs from the verified TypeScript checkpoint, commit 3616024."""

import json
from pathlib import Path

from julius.optimizer import optimize
from julius.reporting import report

FIXTURES = Path(__file__).parents[1] / "fixtures"


def _legacy_projection(actual: object, expected: object) -> object:
    """Keep frozen v1 values exact while allowing additive report fields."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict)
        return {key: _legacy_projection(actual[key], value) for key, value in expected.items()}
    if isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected)
        return [_legacy_projection(item, value) for item, value in zip(actual, expected, strict=True)]
    return actual


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
    assert _legacy_projection(report(events, window), expected) == expected
