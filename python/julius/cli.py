"""Local command interface. Reports never call a model."""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import cast
from uuid import uuid4

from . import __version__
from .events import validate_event
from .economics import analyze_task
from .importers import import_claude_transcript, import_codex_rollout
from .models import discover_ollama, doctor
from .query import query_window
from .reporting import render_csv, render_html, render_text, report
from .sdk import Julius
from .jev import Action, ShadowPolicy, TypeSafeGateway
from .stdio_api import serve_stdio
from .artifacts import ArtifactStore
from .claude_hooks import post_tool_use
from .mcp_recovery import serve_stdio as serve_recovery_stdio
from .claude_runner import run_claude
from .lmstudio import discover_lmstudio


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Julius: local evidence-aware context tools. No hidden model calls.",
        epilog=(
            "Explicit model commands: run --agent grok --request request.json --project id "
            "or run --agent claude --project id. "
            "and jev shadow --state-file state.json --project id --post-call-threshold-usd amount. "
            "Reports never call a model."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"julius-local {__version__} (Python + Rust)"
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=[
            "setup",
            "doctor",
            "models",
            "import",
            "optimize",
            "restore",
            "artifacts",
            "savings",
            "usage",
            "export",
            "dashboard",
            "run",
            "integrations",
            "jev",
            "serve",
            "hook",
            "mcp",
        ],
    )
    parser.add_argument("arguments", nargs="*")
    parser.add_argument("--data-dir", default=os.environ.get("JULIUS_HOME", ".julius"))
    parser.add_argument(
        "--since", default="7d", help="Rolling days/hours/minutes or ISO time; inclusive start"
    )
    parser.add_argument("--until", help="Exclusive end; local dates convert to UTC")
    for option in ("project", "task", "model", "source", "endpoint", "output", "agent", "request", "session", "state-file", "actions", "price-source", "price-date", "baseline", "prices", "overhead"):
        parser.add_argument(f"--{option}")
    for option in ("post-call-threshold-usd", "input-usd-per-million", "output-usd-per-million", "confidence"):
        parser.add_argument(f"--{option}", type=float)
    parser.add_argument("--by", choices=["model", "category", "client"])
    parser.add_argument("--runtime", choices=["ollama", "lmstudio"], default="ollama")
    parser.add_argument("--format")
    parser.add_argument("--profile", choices=["observe", "safe"], default="observe")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--explain", action="store_true")
    parser.add_argument("--coverage-complete", action="store_true", help="Attest that every call in this task window was observed")
    parser.add_argument("--recovery-available", action="store_true", help="Attest that the same project-scoped recovery MCP tool is registered and working")
    parser.add_argument("--recovery-verified", action="store_true", help="Attest that Claude can invoke the matching project recovery tool in this session")
    parser.add_argument("--restore-loop", action="store_true", help="Explicitly serve only Julius restore function calls in xAI Responses")
    parser.add_argument("--max-restore-calls", type=int, default=4)
    return parser


def _required(value: str | None, name: str) -> str:
    if not value:
        raise ValueError(f"Missing {name}")
    return value


def _read(path: str, limit: int) -> str:
    with open(path, "rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"Input exceeds {limit} bytes")
    return data.decode("utf-8")


def _json(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))


def _json_file(path: str, limit: int = 1_000_000) -> object:
    return json.loads(_read(path, limit))


def _task_explanation(data: dict) -> str:
    def value(item: object) -> str:
        return "unavailable" if item is None else str(item)

    return "\n".join([
        f"Task: {data['taskId']}",
        f"Coverage complete: {data['coverageComplete']}",
        f"Observed input tokens: {value(data['observedInputTokens'])}",
        f"Observed output tokens: {value(data['observedOutputTokens'])}",
        f"Direct sent-request input reduction: {value(data['directInputReductionTokens'])}",
        f"Comparative task output difference: {value(data['outputSavingsTokens'])}; evidence: {value(data['outputSavingsEvidence'])}",
        f"Baseline: {value(data['baselineId'])}; evidence: {value(data['baselineEvidence'])}",
        f"Baseline modeled cost USD: {value(data['baselineModeledCostUsd'])}",
        f"Current cost USD (provider charge or modeled): {value(data['currentCostUsd'])}",
        f"Extra overhead USD: {data['extraOverheadUsd']}",
        f"Net financial savings USD: {value(data['netModeledSavingsUsd'])}",
        f"Calls without ID: {data['usageRecordsWithoutCallId']}",
    ])


def run(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    command = args.command
    argument = args.arguments[0] if args.arguments else None
    if not command:
        parser.print_help()
        return 0
    if command == "doctor":
        _json(doctor())
        return 0
    if command == "mcp":
        if args.arguments != ["recovery"]:
            raise ValueError("Use mcp recovery --project <id>")
        root = Path(args.data_dir).absolute() / "artifacts"
        serve_recovery_stdio(ArtifactStore(root), _required(args.project, "--project"))
        return 0
    if command == "hook":
        if args.arguments != ["claude-post-tool-use"]:
            raise ValueError("Use hook claude-post-tool-use --project <id> --profile safe")
        project_id = _required(args.project, "--project")
        raw = sys.stdin.buffer.read(64 * 1024 + 1)
        if len(raw) > 64 * 1024:
            return 0
        try:
            event = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError):
            return 0
        if not isinstance(event, dict):
            return 0
        if args.profile != "safe" or not args.recovery_available:
            return 0
        session_id = event.get("session_id")
        session_id = session_id if isinstance(session_id, str) and session_id else str(uuid4())
        tool_use_id = event.get("tool_use_id")
        source_event_id = (
            f"{session_id}:{tool_use_id}"
            if isinstance(tool_use_id, str) and tool_use_id else str(uuid4())
        )
        with Julius(Path(args.data_dir).absolute()) as julius:
            def record_candidate(artifact: dict, receipt: dict) -> None:
                event_id = str(uuid4())
                julius.ledger.record({
                    "schemaVersion": 1,
                    "eventId": event_id,
                    "occurredAt": datetime.now(timezone.utc).isoformat(
                        timespec="milliseconds"
                    ).replace("+00:00", "Z"),
                    "sourceId": "claude-posttooluse-v1",
                    "sourceEventId": source_event_id,
                    "projectId": project_id,
                    "taskId": args.task,
                    "sessionId": session_id,
                    "requestId": None,
                    "attemptId": None,
                    "clientId": "claude-code",
                    "adapterVersion": "0.1.0-experimental",
                    "modelId": None,
                    "providerId": None,
                    "executionLocation": "unknown",
                    "eventType": "transform",
                    "evidence": "heuristic_estimate",
                    "payload": {
                        "scope": "tool_output",
                        "inputTokens": receipt["beforeTokens"],
                        "outputTokens": receipt["afterTokens"],
                        "tokenizer": None,
                        "transformId": event_id,
                        "parentTransformId": None,
                        "inputArtifactId": artifact["id"],
                        "outputArtifactId": None,
                        "strategy": receipt["reason"],
                        "sent": False,
                    },
                })

            result = post_tool_use(
                event,
                policy={"mode": "safe", "approved": True, "version": "1.0.0"},
                store=julius.artifacts,
                project_id=project_id,
                recovery_available=True,
                candidate_receipt=record_candidate,
            )
        if result is not None:
            print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    if command == "models":
        if argument != "list":
            raise ValueError("Use models list")
        _json(
            discover_lmstudio(args.endpoint or "http://127.0.0.1:1234")
            if args.runtime == "lmstudio"
            else discover_ollama(args.endpoint or "http://127.0.0.1:11434")
        )
        return 0
    if command == "run" and args.agent not in ("grok", "xai", "claude"):
        raise ValueError("Run requires --agent grok or --agent claude")
    if command == "run" and args.agent == "claude":
        if args.arguments or args.request or args.task or args.restore_loop:
            raise ValueError("Claude runner does not yet accept request files, positional arguments, or task attribution")
        if args.profile == "safe" and not args.recovery_verified:
            raise ValueError("Claude safe profile requires --recovery-verified after checking session recovery")
        return run_claude(
            project_id=_required(args.project, "--project"),
            data_dir=Path(args.data_dir).absolute(),
            enable_safe_hook=args.profile == "safe",
            recovery_verified=args.recovery_verified,
        )
    if command == "integrations":
        if argument != "remove":
            raise ValueError("Use integrations remove <id>")
        print("No managed integrations exist. No client configuration was changed.")
        return 0
    if command == "jev" and argument != "shadow":
        raise ValueError("Use jev shadow --state-file <json> --project <id> --post-call-threshold-usd <amount>")
    directory = Path(args.data_dir).absolute()
    if command == "serve":
        if args.arguments:
            raise ValueError("Use serve without positional arguments")
        serve_stdio(directory, sys.stdin, sys.stdout)
        return 0
    with Julius(directory) as julius:
        if command == "jev":
            key = os.environ.get("TYPESAFE_API_KEY")
            if not key:
                raise ValueError("TYPESAFE_API_KEY is required for an explicit Jev shadow call")
            state = json.loads(_read(_required(args.state_file, "--state-file"), 16_384))
            if not isinstance(state, dict):
                raise ValueError("Jev state must be a JSON object")
            actions = tuple((args.actions or "keep,retrieve,compress").split(","))
            if any(action not in ("keep", "retrieve", "compress") for action in actions):
                raise ValueError("Jev actions must be keep, retrieve, or compress")
            gateway = TypeSafeGateway(
                key,
                input_usd_per_million=args.input_usd_per_million,
                output_usd_per_million=args.output_usd_per_million,
            )
            result = julius.evaluate_jev_shadow(
                state=state,
                eligible_actions=cast(tuple[Action, ...], actions),
                policy=ShadowPolicy(
                    enabled=True,
                    max_cost_usd=args.post_call_threshold_usd or 0.0,
                    minimum_confidence=args.confidence if args.confidence is not None else 0.8,
                ),
                project_id=_required(args.project, "--project"),
                session_id=args.session or str(uuid4()),
                task_id=args.task,
                gateway=gateway,
                price_source=args.price_source,
                price_date=args.price_date,
            )
            _json(result)
            return 0
        if command == "run":
            key = os.environ.get("XAI_API_KEY")
            if not key:
                raise ValueError("XAI_API_KEY is required for explicit xAI execution")
            request_path = _required(args.request, "--request")
            request = json.loads(_read(request_path, 2_000_000))
            if not isinstance(request, dict):
                raise ValueError("xAI request must be a JSON object")
            if args.profile == "safe" and args.restore_loop:
                raise ValueError("Safe xAI profile already includes the restore loop")
            common = {
                "api_key": key,
                "project_id": _required(args.project, "--project"),
                "session_id": args.session or str(uuid4()),
                "task_id": args.task,
            }
            if args.profile == "safe":
                result = julius.send_xai_optimized(
                    request, **common,
                    policy={"mode": "safe", "approved": True, "version": "1.0.0"},
                    max_calls=args.max_restore_calls,
                )
            elif args.restore_loop:
                result = julius.send_xai_with_restores(
                    request, **common, max_calls=args.max_restore_calls,
                )
            else:
                result = julius.send_xai(request, **common)
            _json(result)
            return 0 if result["complete"] else 2
        if command == "setup":
            _json(
                {
                    "product": "julius-local",
                    "storage": str(directory),
                    "configurationChanges": [],
                    "doctor": doctor(),
                }
            )
        elif command == "import":
            text = _read(_required(argument, "JSONL file"), 16 * 1024 * 1024)
            format_name = args.format or "julius"
            if format_name == "julius":
                events = [
                    validate_event(json.loads(line)) for line in text.splitlines() if line.strip()
                ]
            elif format_name in ("claude", "codex"):
                importer = (
                    import_claude_transcript if format_name == "claude" else import_codex_rollout
                )
                events = importer(
                    text,
                    {
                        "projectId": _required(args.project, "--project"),
                        "sourceId": _required(args.source, "--source"),
                    },
                )
            else:
                raise ValueError("Import --format must be julius, claude, or codex")
            receipts = julius.ledger.record_many(events)
            _json(
                {
                    "imported": sum(item["inserted"] for item in receipts),
                    "duplicates": sum(not item["inserted"] for item in receipts),
                }
            )
        elif command == "optimize":
            content = _read(_required(argument, "input file"), 1024 * 1024)
            _json(
                julius.optimize(
                    {
                        "projectId": _required(args.project, "--project"),
                        "content": content,
                        "category": "tool_output",
                    },
                    {"mode": args.profile, "version": "1.0.0", "approved": args.profile == "safe"},
                )
            )
        elif command == "restore":
            sys.stdout.write(
                julius.artifacts.get(
                    _required(args.project, "--project"), _required(argument, "artifact ID")
                )
            )
        elif command == "artifacts":
            project = _required(args.project, "--project")
            if argument == "purge":
                _json({"removed": julius.artifacts.purge_expired(project)})
            elif argument == "delete":
                reference = args.arguments[1] if len(args.arguments) > 1 else None
                julius.artifacts.delete(project, _required(reference, "artifact ID"))
                print("Original deleted. Metadata may no longer be recountable.")
            else:
                raise ValueError("Use artifacts delete <id> or artifacts purge --project <id>")
        else:
            window = query_window({"since": args.since, "until": args.until})
            filters = {"since": window["since"], "until": window["until"]}
            filters.update(
                {
                    key: value
                    for key, value in (
                        ("projectId", args.project),
                        ("taskId", args.task),
                        ("modelId", args.model),
                    )
                    if value
                }
            )
            if command == "savings" and args.explain:
                _required(args.task, "--task")
                if args.model:
                    raise ValueError("Task economics cannot filter by model without losing call coverage")
                baseline = _json_file(args.baseline) if args.baseline else None
                prices = _json_file(args.prices) if args.prices else None
                overhead = _json_file(args.overhead) if args.overhead else []
                if baseline is not None and not isinstance(baseline, dict):
                    raise ValueError("Baseline must be a JSON object")
                if prices is not None and not isinstance(prices, dict):
                    raise ValueError("Prices must be a JSON object keyed by snapshot ID")
                if not isinstance(overhead, list):
                    raise ValueError("Overhead must be a JSON array")
                analysis = analyze_task(
                    julius.ledger.events(filters), baseline=baseline, prices=prices,
                    overhead=overhead, coverage_complete=args.coverage_complete,
                )
                if args.json:
                    _json(analysis)
                else:
                    print(_task_explanation(analysis))
                return 0
            data = report(
                julius.ledger.events(filters),
                window,
                args.by or ("category" if command == "usage" else "model"),
            )
            if command == "dashboard":
                destination = _required(args.output, "--output")
                fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(render_html(data))
                print(f"Local HTML report written to {destination}")
            elif command == "export":
                if args.format == "json":
                    _json(data)
                elif args.format in (None, "csv"):
                    print(render_csv(data), end="")
                else:
                    raise ValueError("Export --format must be csv or json")
            elif args.json:
                _json(data)
            else:
                print(render_text(data))
    return 0


def main() -> None:
    try:
        raise SystemExit(run())
    except (ValueError, OSError, RuntimeError, KeyError, TypeError, sqlite3.Error) as error:
        print(f"Julius: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
