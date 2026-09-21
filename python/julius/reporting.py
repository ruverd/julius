"""Offline aggregates. Evidence remains separate from counterfactual claims."""

import csv
import html
import io
from collections import defaultdict
from collections.abc import Sequence
from typing import Any


def _sum(values: Sequence[int | float | None]) -> dict[str, Any]:
    known = sum(value for value in values if value is not None)
    unknown = sum(value is None for value in values)
    return {
        "known": known,
        "unknownRecords": unknown,
        "total": known if values and not unknown else None,
    }


def report(events: list[dict], window: dict, by: str = "model") -> dict[str, Any]:
    if by not in ("model", "client", "category"):
        raise ValueError("Group must be model, client, or category")
    usage = [event for event in events if event["eventType"] == "usage"]
    transforms = [
        event for event in events if event["eventType"] == "transform" and event["payload"]["sent"]
    ]
    groups: dict[str, list[dict]] = defaultdict(list)
    reductions: dict[tuple, list[int | None]] = defaultdict(list)
    for event in usage:
        key = (
            (event.get("modelId") or "unknown")
            if by == "model"
            else (event["clientId"] if by == "client" else event["payload"]["category"])
        )
        groups[key].append(event)
    for event in transforms:
        payload = event["payload"]
        key = (payload["scope"], event["evidence"], payload["tokenizer"], event["modelId"])
        before, after = payload["inputTokens"], payload["outputTokens"]
        reductions[key].append(None if before is None or after is None else before - after)

    def request_key(event: dict) -> tuple | None:
        return (
            (event["projectId"], event["sessionId"], event["requestId"], event["attemptId"])
            if event["requestId"] is not None
            else None
        )

    observed = {request_key(event) for event in usage} - {None}
    transformed = {request_key(event) for event in transforms} & observed

    def costs(items: list[dict]) -> list[float | None]:
        return [event["payload"]["costUsd"] if event["modelId"] else None for event in items]

    return {
        "schemaVersion": 1,
        "period": {**window, "interval": "[since, until)"},
        "sources": sorted({event["sourceId"] for event in events}),
        "observedCalls": sum(
            event["payload"].get("observationScope") != "session_delta" for event in usage
        ),
        "sessionUsageDeltas": sum(
            event["payload"].get("observationScope") == "session_delta" for event in usage
        ),
        "incompleteCalls": sum(not event["payload"]["complete"] for event in usage),
        "unknownModels": sum(event["modelId"] is None for event in usage),
        "coverage": {
            "transformedObservedRequests": len(transformed),
            "observedRequestsWithId": len(observed),
            "scope": "Imported or instrumented requests only; unobserved traffic is unknown.",
        },
        "directInputReduction": [
            {
                "scope": key[0],
                "evidence": key[1],
                "tokenizer": key[2],
                "modelId": key[3],
                "tokens": _sum(values),
            }
            for key, values in reductions.items()
        ],
        "candidateTransformsNotCounted": sum(
            event["eventType"] == "transform" and not event["payload"]["sent"] for event in events
        ),
        "modeledCostUsd": _sum(costs(usage)),
        "auxiliaryCostUsd": _sum(
            costs([e for e in usage if e["payload"]["category"] != "primary"])
        ),
        "financialSavingsUsd": None,
        "baseline": "Unavailable: no comparable financial baseline was recorded.",
        "taskMeasurement": "Incomplete: instrumentation does not establish that every call of a task was captured.",
        "groups": [
            {
                "key": key,
                "calls": len(items),
                **{
                    name: _sum([item["payload"][field] for item in items])
                    for name, field in (
                        ("input", "inputTokens"),
                        ("output", "outputTokens"),
                        ("cacheRead", "cacheReadTokens"),
                        ("cacheWrite", "cacheWriteTokens"),
                    )
                },
                "costUsd": _sum(costs(items)),
                "evidence": sorted({item["evidence"] for item in items}),
                "locations": sorted({item["executionLocation"] for item in items}),
            }
            for key, items in groups.items()
        ],
    }


def _display(value: Any) -> str:
    return "unavailable" if value is None else str(value)


def render_text(data: dict) -> str:
    period = data["period"]
    lines = [
        "Julius — evidence-aware report",
        f"Period: {period['since']} ≤ time < {period['until']} ({period['timezone']})",
        f"Sources: {', '.join(data['sources']) or 'none'}",
        f"Observed calls: {data['observedCalls']}; incomplete: {data['incompleteCalls']}; unknown model: {data['unknownModels']}",
        f"Session usage deltas: {data['sessionUsageDeltas']} (not a known call count)",
        f"Coverage: {data['coverage']['transformedObservedRequests']}/{data['coverage']['observedRequestsWithId']} observed requests with IDs transformed",
    ]
    lines.extend(
        f"Direct input reduction: {_display(item['tokens']['total'])} tokens; known subtotal {item['tokens']['known']}; {item['scope']}; {item['evidence']}; tokenizer {item['tokenizer'] or 'unknown'}"
        for item in data["directInputReduction"]
    )
    if not data["directInputReduction"]:
        lines.append("Direct input reduction: unavailable (no sent transformation evidence)")
    lines.extend(
        [
            f"Modeled cost USD: {_display(data['modeledCostUsd']['total'])}; known subtotal: {data['modeledCostUsd']['known']}",
            f"Observed auxiliary modeled cost USD: {_display(data['auxiliaryCostUsd']['total'])}",
            f"Estimated financial savings USD: unavailable. {data['baseline']}",
            f"Task measurement: {data['taskMeasurement']}",
        ]
    )
    lines.extend(
        f"{group['key']}: calls={group['calls']}, input={_display(group['input']['total'])}, output={_display(group['output']['total'])}, evidence={','.join(group['evidence'])}"
        for group in data["groups"]
    )
    return "\n".join(lines)


def render_csv(data: dict) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(
        ["group", "calls", "input_tokens", "output_tokens", "modeled_cost_usd", "evidence"]
    )
    for group in data["groups"]:
        row = [
            group["key"],
            group["calls"],
            group["input"]["total"],
            group["output"]["total"],
            group["costUsd"]["total"],
            ";".join(group["evidence"]),
        ]
        cells = [_display(value) for value in row]
        writer.writerow(
            [
                "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value
                for value in cells
            ]
        )
    return output.getvalue()


def render_html(data: dict) -> str:
    rows = "".join(
        f"<tr><th scope='row'>{html.escape(group['key'])}</th><td>{group['calls']}</td><td>{_display(group['input']['total'])}</td><td>{_display(group['output']['total'])}</td></tr>"
        for group in data["groups"]
    )
    return (
        "<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
        "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        "<title>Julius evidence report</title><style>:root{color-scheme:light dark}body{font:16px system-ui;max-width:1000px;margin:3rem auto;padding:1rem}pre{white-space:pre-wrap;line-height:1.7}table{border-collapse:collapse;width:100%}td,th{padding:.7rem;text-align:left;border-bottom:1px solid #888}</style>"
        f"<main><h1>Julius</h1><p>Local evidence report. No model calls or external resources.</p><pre>{html.escape(render_text(data))}</pre>"
        "<table><caption>Observed usage</caption><thead><tr><th scope='col'>Group</th><th scope='col'>Records</th><th scope='col'>Input</th><th scope='col'>Output</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></main></html>"
    )
