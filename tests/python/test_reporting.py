import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from julius.query import query_window
from julius.reporting import render_csv, render_html, render_text, report

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


def test_request_and_nested_tool_output_reductions_remain_separate():
    events = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    tool = {**events[0], "eventId": "tool-transform", "sourceEventId": "tool-transform"}
    tool["payload"] = {
        **events[0]["payload"], "scope": "tool_output", "transformId": "tool-transform",
        "inputTokens": 2000, "outputTokens": 500,
    }
    result = report([*events, tool], WINDOW)
    assert result["directInputReduction"][0]["tokens"]["total"] == 7000
    assert result["toolOutputReduction"][0]["tokens"]["total"] == 1500
    assert result["dailySeries"][0]["directInputReduction"]["total"] == 7000
    assert result["dailySeries"][0]["toolOutputReduction"]["total"] == 1500
    assert result["tasks"][0]["directInputReduction"]["total"] == 7000
    assert result["tasks"][0]["toolOutputReduction"]["total"] == 1500
    assert result["coverage"]["transformedObservedRequests"] == 1
    page = render_html(result)
    assert "Direct request input reduction" in page
    assert "Tool-output reduction" in page

    tool_only = report([tool, events[-1]], WINDOW)
    assert tool_only["directInputReduction"] == []
    assert tool_only["toolOutputReduction"][0]["tokens"]["total"] == 1500
    assert tool_only["coverage"]["transformedObservedRequests"] == 0


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


def test_session_delta_with_request_id_is_not_request_coverage() -> None:
    event = json.loads(FIXTURE.read_text().splitlines()[-1])
    event["requestId"] = "client-session-id"
    event["attemptId"] = "session-delta"
    event["payload"]["observationScope"] = "session_delta"
    event["payload"]["callId"] = None
    result = report([event], WINDOW)
    assert result["sessionUsageDeltas"] == 1
    assert result["observedCalls"] == 0
    assert result["coverage"]["observedRequestsWithId"] == 0
    assert result["coverage"]["transformedObservedRequests"] == 0


def test_client_estimates_and_provider_charges_have_distinct_evidence():
    def usage(name: str, provenance: dict, cost: float) -> dict:
        return {
            "eventType": "usage", "sourceId": name, "projectId": "p", "taskId": "task",
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
    assert result["callCostUsd"] == {"known": pytest.approx(0.06), "unknownRecords": 0,
                                     "total": pytest.approx(0.06)}
    assert result["costSources"] == ["client_estimate", "price_model", "provider_charge"]
    assert result["tasks"][0]["callCostUsd"]["total"] == pytest.approx(0.06)
    assert result["groups"][0]["callCostUsd"]["total"] == pytest.approx(0.06)
    assert "Call cost USD (mixed evidence)" in render_html(result)
    assert "Call cost USD (mixed evidence" in render_text(result)
    assert "call_cost_usd" in render_csv(result)


def test_call_cost_remains_unknown_when_one_included_usage_lacks_money():
    event = json.loads(FIXTURE.read_text().splitlines()[-1])
    event["payload"]["costUsd"] = None
    event["payload"]["costProvenance"] = None
    result = report([event], WINDOW)
    assert result["callCostUsd"] == {"known": 0, "unknownRecords": 1, "total": None}
    assert result["costSources"] == ["unknown"]


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
        "observedTaskIds": 1,
        "attempted": 1, "resolved": 1, "withOutcome": 1,
        "scope": "Attempted requires usage, outcome, or a sent transform; outcome and call coverage may be incomplete.",
    }
    task = result["tasks"][0]
    assert (task["input"]["total"], task["output"]["total"]) == (10, None)
    assert (task["cacheRead"]["total"], task["cacheWrite"]["total"]) == (3, 2)
    assert task["auxiliaryUsageRecords"] == 1
    assert task["incompleteUsageRecords"] == 1
    page = render_html(result)
    assert "Observed task IDs: 1; attempted: 1; resolved: 1; with outcome: 1" in page
    assert "[since, until)" in page
    assert "#usage-table tbody tr" in page


def test_candidate_only_task_id_is_not_attempted():
    event = json.loads(FIXTURE.read_text().splitlines()[0])
    event["taskId"] = "candidate-only"
    event["payload"]["sent"] = False
    result = report([event], WINDOW)
    assert result["taskSummary"]["observedTaskIds"] == 1
    assert result["taskSummary"]["attempted"] == 0
    assert result["tasks"] == []
    event["payload"]["sent"] = True
    sent = report([event], WINDOW)
    assert sent["taskSummary"]["attempted"] == 1


def test_task_table_filters_and_local_visible_row_export():
    event = json.loads(FIXTURE.read_text().splitlines()[-1])
    event.update(taskId="task-1", projectId="safe-project")
    other = {**event, "eventId": "other-usage", "sourceEventId": "other-usage",
             "taskId": "task-2", "projectId": "another-project"}
    outcome = {**event, "eventId": "task-outcome", "eventType": "outcome",
               "payload": {"outcome": "resolved", "reason": None}}
    page = render_html(report([event, other, outcome], WINDOW))
    assert "id='task-table'" in page
    assert "<label for='task-outcome'>Outcome</label>" in page
    assert "<label for='task-project'>Project</label>" in page
    assert "data-outcome='resolved' data-project='safe-project'" in page
    assert "data-outcome='unavailable' data-project='another-project'" in page
    assert "id='task-row-count' role='status' aria-live='polite'" in page
    assert "row.hidden=!match" in page
    assert "filter(row=>!row.hidden)" in page
    assert "URL.createObjectURL(new Blob([csv]" in page
    assert "URL.revokeObjectURL(url)" in page


def test_unsafe_project_ids_are_not_filter_options_or_data_attributes():
    event = json.loads(FIXTURE.read_text().splitlines()[-1])
    event.update(taskId="task-1", projectId="/private/work")
    page = render_html(report([event], WINDOW))
    assert "[redacted path]" in page
    assert "id='task-project'" not in page
    assert "data-project=" not in page
    assert "/private/work" not in page
