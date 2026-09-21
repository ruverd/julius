"""Offline aggregates. Evidence remains separate from counterfactual claims."""

import csv
import html
import io
import re
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
    def call_identity(event: dict) -> tuple | None:
        payload = event["payload"]
        call_id = payload.get("callId")
        return (
            (event["projectId"], event["sessionId"], event["clientId"],
             event.get("providerId"), call_id)
            if isinstance(call_id, str) and call_id
            and payload.get("observationScope") != "session_delta"
            else None
        )

    known_calls = {call_identity(event) for event in usage} - {None}
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

    # A task ID can be attached to a preview or decision before any attempt.
    # Outcome is a separate fact; usage alone cannot establish resolution.
    task_events: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for event in events:
        if event.get("taskId"):
            task_events[(event["projectId"], event["taskId"])].append(event)
    task_rows = []
    for (project_id, task_id), items in sorted(task_events.items()):
        task_usage = [item for item in items if item["eventType"] == "usage"]
        outcomes = [item for item in items if item["eventType"] == "outcome"]
        latest = max(outcomes, key=lambda item: (item["occurredAt"], item["eventId"])) if outcomes else None
        outcome = latest["payload"]["outcome"] if latest else None
        task_transforms = [item for item in items if item["eventType"] == "transform" and item["payload"]["sent"]]
        if not (task_usage or outcomes or task_transforms):
            continue
        task_rows.append({
            "projectId": project_id, "taskId": task_id, "outcome": outcome,
            "resolved": outcome == "resolved",
            "observedCalls": len({call_identity(item) for item in task_usage} - {None}),
            "usageRecords": len(task_usage),
            "incompleteUsageRecords": sum(not item["payload"]["complete"] for item in task_usage),
            "input": _sum([item["payload"]["inputTokens"] for item in task_usage]),
            "output": _sum([item["payload"]["outputTokens"] for item in task_usage]),
            "cacheRead": _sum([item["payload"]["cacheReadTokens"] for item in task_usage]),
            "cacheWrite": _sum([item["payload"]["cacheWriteTokens"] for item in task_usage]),
            "auxiliaryUsageRecords": sum(item["payload"]["category"] != "primary" for item in task_usage),
            "directInputReduction": _sum([
                None if item["payload"]["inputTokens"] is None or item["payload"]["outputTokens"] is None
                else item["payload"]["inputTokens"] - item["payload"]["outputTokens"]
                for item in task_transforms
            ]),
        })

    def costs(items: list[dict], *, basis: str = "estimated") -> list[float | None]:
        values: list[float | None] = []
        for event in items:
            provenance = event["payload"].get("costProvenance") or {}
            charge = provenance.get("chargeSource") == "provider_usage"
            client = provenance.get("estimateSource") == "client_result"
            included = (
                charge if basis == "provider_charge" else
                client if basis == "client_estimate" else
                not charge and not client if basis == "price_model" else
                not charge
            )
            values.append(event["payload"]["costUsd"] if event["modelId"] and included else None)
        return values

    result = {
        "schemaVersion": 1,
        "period": {**window, "interval": "[since, until)"},
        "sources": sorted({event["sourceId"] for event in events}),
        "observedCalls": len(known_calls),
        "usageRecords": len(usage),
        "usageRecordsWithoutCallId": sum(call_identity(event) is None for event in usage),
        "sessionUsageDeltas": sum(
            event["payload"].get("observationScope") == "session_delta" for event in usage
        ),
        "incompleteCalls": len({call_identity(event) for event in usage
                                if call_identity(event) is not None
                                and not event["payload"]["complete"]}),
        "incompleteUsageRecords": sum(not event["payload"]["complete"] for event in usage),
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
        "clientEstimatedCostUsd": _sum(costs(usage, basis="client_estimate")),
        "priceModeledCostUsd": _sum(costs(usage, basis="price_model")),
        "auxiliaryCostUsd": _sum(
            costs([e for e in usage if e["payload"]["category"] != "primary"])
        ),
        "financialSavingsUsd": None,
        "baseline": "Unavailable: no comparable financial baseline was recorded.",
        "taskMeasurement": "Incomplete: instrumentation does not establish that every call of a task was captured.",
        "taskSummary": {
            "observedTaskIds": len(task_events),
            "attempted": len(task_rows),
            "resolved": sum(item["resolved"] for item in task_rows),
            "withOutcome": sum(item["outcome"] is not None for item in task_rows),
            "scope": "Attempted requires usage, outcome, or a sent transform; outcome and call coverage may be incomplete.",
        },
        "tasks": task_rows,
        "groups": [
            {
                "key": key,
                "calls": len({call_identity(item) for item in items} - {None}),
                "usageRecords": len(items),
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
                "clientEstimatedCostUsd": _sum(costs(items, basis="client_estimate")),
                "priceModeledCostUsd": _sum(costs(items, basis="price_model")),
                "evidence": sorted({item["evidence"] for item in items}),
                "locations": sorted({item["executionLocation"] for item in items}),
            }
            for key, items in groups.items()
        ],
    }
    if any((event["payload"].get("costProvenance") or {}).get("chargeSource") == "provider_usage" for event in usage):
        result["providerChargedUsd"] = _sum(costs(usage, basis="provider_charge"))
        for group, items in zip(result["groups"], groups.values(), strict=True):
            group["providerChargedUsd"] = _sum(costs(items, basis="provider_charge"))
    return result


def _display(value: Any) -> str:
    return "unavailable" if value is None else str(value)


def render_text(data: dict) -> str:
    period = data["period"]
    lines = [
        "Julius — evidence-aware report",
        f"Period: {period['since']} ≤ time < {period['until']} ({period['timezone']})",
        f"Sources: {', '.join(data['sources']) or 'none'}",
        f"Observed calls with IDs: {data['observedCalls']}; incomplete calls: {data['incompleteCalls']}; unknown-model usage records: {data['unknownModels']}",
        f"Usage records: {data.get('usageRecords', data['observedCalls'])}; without call ID: {data.get('usageRecordsWithoutCallId', 0)}; incomplete records: {data.get('incompleteUsageRecords', data['incompleteCalls'])}",
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
            f"Estimated cost USD (non-provider): {_display(data['modeledCostUsd']['total'])}; known subtotal: {data['modeledCostUsd']['known']}",
            f"Client-estimated cost USD: {_display(data['clientEstimatedCostUsd']['total'])}; known subtotal: {data['clientEstimatedCostUsd']['known']}",
            f"Price-modeled cost USD: {_display(data['priceModeledCostUsd']['total'])}; known subtotal: {data['priceModeledCostUsd']['known']}",
            f"Observed auxiliary modeled cost USD: {_display(data['auxiliaryCostUsd']['total'])}",
            f"Estimated financial savings USD: unavailable. {data['baseline']}",
            f"Task measurement: {data['taskMeasurement']}",
        ]
    )
    if "providerChargedUsd" in data:
        lines.append(
            f"Provider-reported charge USD: {_display(data['providerChargedUsd']['total'])}; "
            f"known subtotal: {data['providerChargedUsd']['known']}"
        )
    lines.extend(
        f"{group['key']}: calls={group['calls']}, records={group.get('usageRecords', group['calls'])}, input={_display(group['input']['total'])}, output={_display(group['output']['total'])}, evidence={','.join(group['evidence'])}"
        for group in data["groups"]
    )
    return "\n".join(lines)


def render_csv(data: dict) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    provider_charges = "providerChargedUsd" in data
    columns = ["group", "calls", "usage_records", "input_tokens", "output_tokens", "modeled_cost_usd"]
    if provider_charges:
        columns.append("provider_charged_usd")
    writer.writerow([*columns, "evidence"])
    for group in data["groups"]:
        row = [
            group["key"],
            group["calls"],
            group.get("usageRecords", group["calls"]),
            group["input"]["total"],
            group["output"]["total"],
            group["costUsd"]["total"],
        ]
        if provider_charges:
            row.append(group["providerChargedUsd"]["total"])
        row.append(";".join(group["evidence"]))
        cells = [_display(value) for value in row]
        writer.writerow(
            [
                "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value
                for value in cells
            ]
        )
    return output.getvalue()


def render_html(data: dict) -> str:
    def cell(value: Any) -> str:
        return html.escape(_display(value), quote=True)

    def measure(value: dict[str, Any]) -> str:
        total = value.get("total")
        unknown = value.get("unknownRecords", 0)
        if total is None:
            return f"unavailable <span class='muted'>(known subtotal {cell(value.get('known'))}; {cell(unknown)} unknown)</span>"
        return cell(total)

    def safe_dimension(value: Any) -> str | None:
        # Project/task labels can originate in client data. Never export path-shaped IDs.
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value):
            return value
        return None

    def public_label(value: Any) -> str:
        label = _display(value)
        if label.startswith(("/", "~/", "\\\\")) or re.match(r"^[A-Za-z]:[\\/]", label):
            return "[redacted path]"
        return label

    group_by = data.get("groupBy")
    dimensions = {"model": "modelId", "client": "clientId"}
    active: dict[str, list[str]] = {}
    for dimension in ("model", "client", "project", "task", "strategy"):
        field = dimensions.get(dimension, {"project": "projectId", "task": "taskId", "strategy": "strategy"}.get(dimension))
        values = []
        for group in data["groups"]:
            value = group.get(field)
            if dimension == group_by and value is None:
                value = group.get("key")
            if dimension in ("project", "task", "strategy"):
                value = safe_dimension(value)
            elif value is not None:
                value = public_label(value)
            if isinstance(value, str) and value:
                values.append(value)
        if values and len(values) == len(data["groups"]):
            active[dimension] = sorted(set(values))
    filters = "".join(
        f"<label for='filter-{name}'>{name.title()}</label>"
        f"<select id='filter-{name}' data-filter='{name}'>"
        f"<option value=''>All {name}s</option>"
        + "".join(f"<option value='{cell(value)}'>{cell(value)}</option>" for value in values)
        + "</select>"
        for name, values in active.items()
    )
    rows = []
    for group in data["groups"]:
        attributes = []
        for name in active:
            field = dimensions.get(name, {"project": "projectId", "task": "taskId", "strategy": "strategy"}.get(name))
            value = group.get(field)
            if name == group_by and value is None:
                value = group.get("key")
            if name in ("model", "client"):
                value = public_label(value)
            attributes.append(f"data-{name}='{cell(value)}'")
        rows.append(
            f"<tr {' '.join(attributes)}><th scope='row'>{cell(public_label(group['key']))}</th>"
            f"<td>{cell(group['calls'])}</td><td>{measure(group['input'])}</td>"
            f"<td>{measure(group['output'])}</td><td>{measure(group['costUsd'])}</td>"
            f"<td>{cell(', '.join(group.get('evidence', [])))}</td></tr>"
        )
    savings = data.get("financialSavingsUsd")
    savings_text = cell(savings) if savings is not None else "unavailable"
    coverage = data.get("coverage")
    coverage_text = (
        f"{cell(coverage['transformedObservedRequests'])}/{cell(coverage['observedRequestsWithId'])}"
        if isinstance(coverage, dict)
        and "transformedObservedRequests" in coverage
        and "observedRequestsWithId" in coverage
        else "unavailable"
    )
    period = data["period"]
    task_summary = data.get("taskSummary", {})
    task_rows = []
    for task in data.get("tasks", []):
        task_rows.append(
            "<tr>"
            f"<th scope='row'>{cell(public_label(task['taskId']))}</th>"
            f"<td>{cell(public_label(task['projectId']))}</td>"
            f"<td>{cell(task['outcome'])}</td>"
            f"<td>{cell(task['observedCalls'])}</td>"
            f"<td>{cell(task['incompleteUsageRecords'])}</td>"
            f"<td>{measure(task['input'])}</td><td>{measure(task['output'])}</td>"
            f"<td>{measure(task['cacheRead'])}</td><td>{measure(task['cacheWrite'])}</td>"
            f"<td>{cell(task['auxiliaryUsageRecords'])}</td>"
            f"<td>{measure(task['directInputReduction'])}</td></tr>"
        )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width'>"
        "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; "
        "style-src 'unsafe-inline'; script-src 'unsafe-inline'\">"
        "<title>Julius evidence report</title><style>"
        ":root{color-scheme:light dark;font:16px system-ui}body{max-width:1100px;margin:2rem auto;padding:1rem;line-height:1.5}"
        "main{display:grid;gap:1.5rem}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(12rem,1fr));gap:.8rem}"
        ".card{border:1px solid #888;border-radius:.5rem;padding:1rem}.card strong{display:block;font-size:1.5rem}"
        ".muted{opacity:.75;font-size:.9em}.filters{display:flex;flex-wrap:wrap;gap:.6rem;align-items:center}"
        "select{font:inherit;padding:.35rem}select:focus-visible,th:focus-visible{outline:3px solid Highlight}"
        ".table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%}th,td{padding:.65rem;text-align:left;border-bottom:1px solid #888;vertical-align:top}"
        "tbody tr:hover{background:CanvasText;color:Canvas}tr[hidden]{display:none}"
        "@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}"
        "</style></head><body><main><header><h1>Julius evidence report</h1>"
        f"<p>Local aggregate for {cell(period['since'])} to {cell(period['until'])} "
        f"({cell(period.get('timezone'))}; [since, until)). "
        "No model calls or external resources.</p></header>"
        "<section class='cards' aria-label='Summary'>"
        f"<div class='card'>Observed calls with IDs<strong>{cell(data['observedCalls'])}</strong></div>"
        f"<div class='card'>Incomplete usage records<strong>{cell(data.get('incompleteUsageRecords', data['incompleteCalls']))}</strong></div>"
        f"<div class='card'>Transformed observed requests<strong>{coverage_text}</strong></div>"
        f"<div class='card'>Session usage deltas<strong>{cell(data.get('sessionUsageDeltas'))}</strong></div>"
        f"<div class='card'>Estimated cost USD (non-provider)<strong>{measure(data['modeledCostUsd'])}</strong></div>"
        f"<div class='card'>Financial savings USD<strong>{savings_text}</strong></div></section>"
        "<section aria-labelledby='tasks-title'><h2 id='tasks-title'>Observed tasks</h2>"
        f"<p>Observed task IDs: {cell(task_summary.get('observedTaskIds'))}; "
        f"attempted: {cell(task_summary.get('attempted'))}; resolved: {cell(task_summary.get('resolved'))}; "
        f"with outcome: {cell(task_summary.get('withOutcome'))}. "
        "Attempted requires usage, an outcome, or a sent transform. Resolved requires an explicit resolved outcome. Full call coverage remains unknown.</p>"
        "<div class='table-wrap'><table><caption>Task usage and sent transformations</caption>"
        "<thead><tr><th scope='col'>Task</th><th scope='col'>Project</th><th scope='col'>Outcome</th>"
        "<th scope='col'>Observed calls</th><th scope='col'>Incomplete usage records</th>"
        "<th scope='col'>Input</th><th scope='col'>Output</th><th scope='col'>Cache read</th>"
        "<th scope='col'>Cache write</th><th scope='col'>Auxiliary records</th>"
        "<th scope='col'>Direct input reduction</th></tr></thead>"
        f"<tbody>{''.join(task_rows)}</tbody></table></div></section>"
        f"<p>{cell(data['baseline'])} {cell(data['taskMeasurement'])}</p>"
        "<section aria-labelledby='usage-title'><h2 id='usage-title'>Observed usage</h2>"
        f"<div class='filters' aria-label='Filter usage table'>{filters}</div>"
        "<p id='row-count' role='status' aria-live='polite'></p>"
        "<div class='table-wrap'><table id='usage-table'><caption>Aggregated usage by group</caption>"
        "<thead><tr><th scope='col'>Group</th><th scope='col'>Records</th>"
        "<th scope='col'>Input tokens</th><th scope='col'>Output tokens</th>"
        "<th scope='col'>Modeled cost USD</th><th scope='col'>Evidence</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div></section></main>"
        "<script type='module'>(()=>{const rows=[...document.querySelectorAll('#usage-table tbody tr')];"
        "const selects=[...document.querySelectorAll('select[data-filter]')];"
        "const count=document.getElementById('row-count');"
        "function update(){let shown=0;for(const row of rows){"
        "const match=selects.every(select=>!select.value||row.dataset[select.dataset.filter]===select.value);"
        "row.hidden=!match;if(match)shown++}count.textContent=`${shown} of ${rows.length} groups shown`;}"
        "for(const select of selects)select.addEventListener('change',update);update()})();</script>"
        "</body></html>"
    )
