"""Offline HTML dashboard contract and privacy checks."""

import json
from pathlib import Path

from julius.reporting import render_html, report


FIXTURE = Path(__file__).parents[1] / "fixtures" / "events.jsonl"


def sample():
    return {
        "period": {"since": "2026-09-21T00:00:00Z", "until": "2026-09-22T00:00:00Z"},
        "groupBy": "model", "observedCalls": 3, "incompleteCalls": 1,
        "modeledCostUsd": {"known": 0.4, "unknownRecords": 1, "total": None},
        "financialSavingsUsd": -0.25,
        "baseline": "Controlled comparison", "taskMeasurement": "Coverage incomplete",
        "sources": ["/Users/private/rollout.jsonl"],
        "groups": [
            {"key": "model-a", "calls": 2, "input": {"known": 30, "unknownRecords": 1, "total": None},
             "output": {"known": 10, "unknownRecords": 0, "total": 10},
             "costUsd": {"known": 0.4, "unknownRecords": 1, "total": None},
             "evidence": ["provider_usage"], "projectId": "project-a", "taskId": "task-a",
             "strategy": "compress"},
            {"key": "model-b", "calls": 1, "input": {"known": 20, "unknownRecords": 0, "total": 20},
             "output": {"known": 5, "unknownRecords": 0, "total": 5},
             "costUsd": {"known": 0.1, "unknownRecords": 0, "total": 0.1},
             "evidence": ["imported"], "projectId": "project-b", "taskId": "task-b",
             "strategy": "observe"},
        ],
    }


def test_filters_accessibility_incomplete_and_signed_values():
    page = render_html(sample())
    for label in ("Model", "Project", "Task", "Strategy"):
        assert f">{label}</label>" in page
    assert "aria-live='polite'" in page
    assert "<th scope='row'>model-a</th>" in page
    assert "known subtotal 30; 1 unknown" in page
    assert "-0.25" in page
    assert "color-scheme:light dark" in page
    assert "https://" not in page
    assert "/Users/private" not in page


def test_missing_dimensions_are_not_invented_and_paths_are_redacted():
    data = sample()
    data["groups"][0]["key"] = "/Users/private/model"
    data["groups"][0]["projectId"] = "/Users/private/project"
    data["groups"][1].pop("taskId")
    page = render_html(data)
    assert "[redacted path]" in page
    assert "/Users/private" not in page
    assert "id='filter-project'" not in page
    assert "id='filter-task'" not in page


def test_html_escapes_group_and_attribute_values():
    data = sample()
    data["groups"][0]["key"] = "<script>alert('x')</script>"
    page = render_html(data)
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page


def test_daily_categories_cache_unknown_and_signed_reduction():
    template = json.loads(FIXTURE.read_text().splitlines()[-1])

    def usage(category, input_tokens, output_tokens, cache_read, day):
        event = {**template, "eventType": "usage", "occurredAt": day}
        event["payload"] = {
            "category": category, "complete": False, "callId": None,
            "inputTokens": input_tokens, "outputTokens": output_tokens,
            "cacheReadTokens": cache_read, "cacheWriteTokens": None, "costUsd": None,
        }
        return event

    primary = usage("primary", 100, 20, 30, "2026-09-21T23:30:00-02:00")
    auxiliary = usage("auxiliary", 10, None, 3, "2026-09-22T01:30:00Z")
    restoration = usage("restoration", None, 4, None, "2026-09-22T02:00:00Z")
    transform = json.loads(FIXTURE.read_text().splitlines()[0])
    transform["occurredAt"] = "2026-09-22T02:00:00Z"
    transform["payload"].update(sent=True, inputTokens=10, outputTokens=30)
    window = {"since": "2026-09-21T00:00:00Z", "until": "2026-09-23T00:00:00Z", "timezone": "UTC"}
    data = report([primary, auxiliary, restoration, transform], window)
    assert len(data["dailySeries"]) == 1
    day = data["dailySeries"][0]
    assert day["dateUtc"] == "2026-09-22"
    assert [part["usageRecords"] for part in day["categories"]] == [1, 1, 1, 0]
    assert day["categories"][0]["input"]["total"] == 100
    assert day["categories"][0]["cacheRead"]["total"] == 30
    assert day["categories"][1]["output"]["total"] is None
    assert day["categories"][2]["input"]["unknownRecords"] == 1
    assert day["auxiliaryOverhead"]["input"]["total"] is None
    assert day["directInputReduction"]["total"] == -20
    assert day["incompleteUsageRecords"] == 3
    page = render_html(data)
    assert "Daily observed usage (UTC)" in page
    assert "-20" in page
    assert "known subtotal 0; 1 unknown" in page
