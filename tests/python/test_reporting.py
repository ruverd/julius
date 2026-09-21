import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from julius.query import query_window
from julius.reporting import render_csv, render_html, report

FIXTURE = Path(__file__).parents[1] / "fixtures" / "events.jsonl"
WINDOW = {
    "since": "2026-09-21T00:00:00.000Z",
    "until": "2026-09-22T00:00:00.000Z",
    "timezone": "UTC",
}


def test_marginal_chain_unknown_money_and_negative_gain():
    events = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    result = report(events, WINDOW)
    assert result["directInputReduction"][0]["tokens"]["total"] == 7000
    assert result["financialSavingsUsd"] is None
    assert result["modeledCostUsd"]["total"] is None
    events[0]["payload"].update(inputTokens=10, outputTokens=30)
    assert report(events[:1], WINDOW)["directInputReduction"][0]["tokens"]["total"] == -20


def test_preview_and_foreign_project_do_not_count_coverage():
    events = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    events[0]["payload"]["sent"] = False
    events[1]["projectId"] = "other"
    result = report(events, WINDOW)
    assert result["candidateTransformsNotCounted"] == 1
    assert result["coverage"]["transformedObservedRequests"] == 0


def test_exports_escape_active_content():
    event = json.loads(FIXTURE.read_text().splitlines()[-1])
    event["clientId"] = "<script>alert(1)</script>"
    assert "<script>" not in render_html(report([event], WINDOW, "client"))
    event["clientId"] = '=HYPERLINK("evil")'
    assert "'=HYPERLINK" in render_csv(report([event], WINDOW, "client"))


def test_query_window_is_rolling_and_rejects_invalid_calendar_dates():
    window = query_window({"since": "7d"}, datetime(2026, 9, 21, 12, 34, 56, tzinfo=timezone.utc))
    assert window["since"] == "2026-09-14T12:34:56.000Z"
    with pytest.raises(ValueError):
        query_window({"since": "2026-02-30"})
