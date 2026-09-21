"""Offline HTML dashboard contract and privacy checks."""

from julius.reporting import render_html


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
