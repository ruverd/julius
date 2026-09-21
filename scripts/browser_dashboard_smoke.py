"""Optional end-user browser smoke for the self-contained HTML dashboard.

Run with ``uv run --with playwright python scripts/browser_dashboard_smoke.py``.
Install Playwright's Chromium first or pass ``--browser-executable``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from julius.events import validate_event
from julius.reporting import render_html, report


def _events() -> list[dict]:
    events = []
    for index, (project, model, outcome) in enumerate(
        (("project-a", "model-a", "resolved"), ("project-b", "model-b", "failed")), 1
    ):
        base = {
            "schemaVersion": 1,
            "occurredAt": "2026-09-21T12:00:00.000Z",
            "sourceId": "dashboard-browser-smoke",
            "projectId": project,
            "taskId": f"task-{index}",
            "sessionId": f"session-{index}",
            "requestId": f"request-{index}",
            "attemptId": f"attempt-{index}",
            "clientId": "fixture-client",
            "adapterVersion": "1",
            "modelId": model,
            "providerId": "fixture-provider",
            "executionLocation": "remote",
            "evidence": "runtime_reported",
        }
        events.append(validate_event({
            **base,
            "eventId": f"usage-{index}",
            "sourceEventId": f"usage-{index}",
            "eventType": "usage",
            "payload": {
                "inputTokens": 100,
                "outputTokens": 20,
                "cacheReadTokens": 0,
                "cacheWriteTokens": 0,
                "complete": True,
                "category": "primary",
                "callId": f"call-{index}",
                "costUsd": index / 100,
                "costProvenance": {
                    "priceSource": "synthetic-browser-smoke",
                    "priceDate": "2026-09-21",
                    "priceModelId": model,
                },
            },
        }))
        events.append(validate_event({
            **base,
            "eventId": f"outcome-{index}",
            "sourceEventId": f"outcome-{index}",
            "eventType": "outcome",
            "payload": {"outcome": outcome, "reason": "synthetic browser check"},
        }))
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-executable", type=Path)
    args = parser.parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit("Install optional Playwright with: uv run --with playwright python scripts/browser_dashboard_smoke.py") from exc

    data = report(_events(), {
        "since": "2026-09-21T00:00:00.000Z",
        "until": "2026-09-22T00:00:00.000Z",
        "timezone": "UTC",
    })
    with tempfile.TemporaryDirectory(prefix="julius-dashboard-browser-") as directory:
        page_file = Path(directory) / "report.html"
        page_file.write_text(render_html(data), encoding="utf-8")
        with sync_playwright() as playwright:
            options = {"headless": True}
            if args.browser_executable is not None:
                options["executable_path"] = str(args.browser_executable)
            browser = playwright.chromium.launch(**options)
            light = browser.new_page(viewport={"width": 1227, "height": 800}, accept_downloads=True)
            light.goto(page_file.as_uri())
            assert light.title() == "Julius evidence report"
            assert light.locator("#row-count").inner_text() == "2 of 2 groups shown"
            task_wrap = light.get_by_role("region", name="Scrollable task details")
            widths = task_wrap.evaluate(
                "node => ({scroll: node.scrollWidth, client: node.clientWidth, "
                "body: document.body.scrollWidth, viewport: innerWidth})"
            )
            assert widths["scroll"] > widths["client"]
            assert widths["body"] <= widths["viewport"]
            task_wrap.focus()
            light.keyboard.press("ArrowRight")
            light.wait_for_timeout(200)
            assert task_wrap.evaluate("node => node.scrollLeft") > 0
            light.locator("#filter-model").select_option("model-a")
            assert light.locator("#row-count").inner_text() == "1 of 2 groups shown"
            light.locator("#task-outcome").select_option("failed")
            assert light.locator("#task-row-count").inner_text() == "1 of 2 tasks shown"
            with light.expect_download() as transfer:
                light.locator("#export-tasks").click()
            exported = Path(transfer.value.path()).read_text(encoding="utf-8")
            assert "task-2" in exported and "task-1" not in exported

            dark = browser.new_page(viewport={"width": 1227, "height": 800}, color_scheme="dark")
            dark.goto(page_file.as_uri())
            assert dark.evaluate("matchMedia('(prefers-color-scheme: dark)').matches")
            assert dark.get_by_role("heading", name="Julius evidence report").is_visible()
            print(json.dumps({
                "status": "passed",
                "browserVersion": browser.version,
                "usageFilter": "1/2",
                "taskFilter": "1/2",
                "visibleCsvOnly": "task-2",
                "keyboardHorizontalScroll": True,
                "lightAndDark": True,
            }))
            browser.close()


if __name__ == "__main__":
    main()
