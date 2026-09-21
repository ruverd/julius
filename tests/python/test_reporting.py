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


def test_session_delta_is_recorded_without_becoming_a_call():
    def usage(source: str, call_id: str | None, scope: str, complete: bool) -> dict:
        return {
            "eventType": "usage", "sourceId": source, "projectId": "p",
            "sessionId": "s", "requestId": None, "attemptId": None,
            "clientId": "cli", "modelId": None, "providerId": None,
            "executionLocation": "unknown", "evidence": "runtime_reported",
            "payload": {"callId": call_id, "observationScope": scope,
                        "complete": complete, "category": "primary",
                        "inputTokens": 10, "outputTokens": 2,
                        "cacheReadTokens": None, "cacheWriteTokens": None,
                        "costUsd": None},
        }

    result = report([
        usage("session", None, "session_delta", False),
        usage("call", "real-call", "call", True),
    ], WINDOW)
    assert result["observedCalls"] == 1
    assert result["usageRecords"] == 2
    assert result["usageRecordsWithoutCallId"] == 1
    assert result["sessionUsageDeltas"] == 1
    assert result["incompleteCalls"] == 0
    assert result["incompleteUsageRecords"] == 1
    assert result["groups"][0]["calls"] == 1
    assert result["groups"][0]["usageRecords"] == 2
    assert "Transformed observed requests" in render_html(result)
    assert "Session usage deltas" in render_html(result)


def test_client_estimates_and_provider_charges_have_distinct_evidence():
    def usage(name: str, provenance: dict, cost: float) -> dict:
        return {
            "eventType": "usage", "sourceId": name, "projectId": "p",
            "sessionId": "s", "requestId": name, "attemptId": name,
            "clientId": "cli", "modelId": "m", "providerId": "vendor",
            "executionLocation": "remote", "evidence": "runtime_reported",
            "payload": {"callId": name, "observationScope": "call",
                        "complete": True, "category": "primary",
                        "inputTokens": 10, "outputTokens": 2,
                        "cacheReadTokens": 0, "cacheWriteTokens": 0,
                        "costUsd": cost, "costProvenance": provenance},
        }

    result = report([
        usage("client", {"estimateSource": "client_result"}, 0.02),
        usage("price", {"priceSource": "fixture"}, 0.01),
        usage("provider", {"chargeSource": "provider_usage"}, 0.03),
    ], WINDOW)
    assert result["modeledCostUsd"]["known"] == pytest.approx(0.03)
    assert result["clientEstimatedCostUsd"]["known"] == pytest.approx(0.02)
    assert result["priceModeledCostUsd"]["known"] == pytest.approx(0.01)
    assert result["providerChargedUsd"]["known"] == pytest.approx(0.03)
    assert result["modeledCostUsd"]["total"] is None


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


def test_task_outcomes_and_separate_usage_measures():
    base = json.loads(FIXTURE.read_text().splitlines()[-1])
    base.update(taskId="task-1", eventType="usage", eventId="usage-1")
    base["payload"] = {
        "callId": "call-1", "observationScope": "call", "complete": False,
        "category": "auxiliary", "inputTokens": 10, "outputTokens": None,
        "cacheReadTokens": 3, "cacheWriteTokens": 2, "costUsd": None,
    }
    outcome = {**base, "eventId": "outcome-1", "eventType": "outcome",
               "payload": {"outcome": "resolved", "reason": None}}
    result = report([base, outcome], WINDOW)
    assert result["taskSummary"] == {
        "attempted": 1, "resolved": 1, "withOutcome": 1,
        "scope": "Tasks with an observed task ID in this period; outcome and call coverage may be incomplete.",
    }
    task = result["tasks"][0]
    assert (task["input"]["total"], task["output"]["total"]) == (10, None)
    assert (task["cacheRead"]["total"], task["cacheWrite"]["total"]) == (3, 2)
    assert task["auxiliaryUsageRecords"] == 1
    assert task["incompleteUsageRecords"] == 1
    page = render_html(result)
    assert "Attempted: 1; resolved: 1; with outcome: 1" in page
    assert "[since, until)" in page
    assert "#usage-table tbody tr" in page
