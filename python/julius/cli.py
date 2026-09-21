"""Local command interface. Reports never call a model."""

import argparse
import hashlib
import json
import os
import shlex
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import cast
from uuid import uuid4

from pydantic import ValidationError

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
from .claude_print_runner import run_claude_print
from .codex_live_probe import probe_codex_usage
from .lmstudio import discover_lmstudio
from .model_registry import ModelRegistry, ModelSnapshot
from .price_store import PriceSnapshot, PriceStore
from .model_scan import scan_models
from .memory import MemoryStore
from .symbols import SymbolStore
from .evaluation_runner import Attempt, FrozenFixture, replay_paired_fixtures
from .integration_manager import ClaudeIntegrationManager
from .quality_guard import GuardPolicy, ManualAction, Scope, TaskOutcome, decide_suspension
from .quality_store import QualityStore


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
            "symbols",
            "prices",
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
            "evaluate",
            "policy",
            "probe",
        ],
    )
    parser.add_argument("arguments", nargs="*")
    parser.add_argument("--data-dir", default=os.environ.get("JULIUS_HOME", ".julius"))
    parser.add_argument(
        "--since", default="7d", help="Rolling days/hours/minutes or ISO time; inclusive start"
    )
    parser.add_argument("--until", help="Exclusive end; local dates convert to UTC")
    for option in ("project", "project-root", "snapshot", "apply-plan", "task", "model", "source", "endpoint", "provider", "currency", "tier", "cache-regime", "at", "output", "agent", "request", "prompt-file", "session", "state-file", "guard-file", "actions", "price-source", "price-date", "baseline", "prices", "overhead"):
        parser.add_argument(f"--{option}")
    for option in ("post-call-threshold-usd", "input-usd-per-million", "output-usd-per-million", "confidence", "max-budget-usd", "timeout-seconds"):
        parser.add_argument(f"--{option}", type=float)
    parser.add_argument("--max-turns", type=int, default=4)
    parser.add_argument("--by", choices=["model", "category", "client"])
    parser.add_argument("--runtime", choices=["ollama", "lmstudio"], default="ollama")
    parser.add_argument("--format")
    parser.add_argument("--profile", choices=["observe", "safe"], default="observe")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--include-raw", action="store_true", help="Include original rawUsage in explicit event JSONL export")
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


def _integration_state_root(data_dir: Path, project_root: Path) -> Path:
    """Keep configuration backups outside the project, even with default .julius."""
    data_dir = data_dir.resolve()
    project_root = project_root.resolve()
    if data_dir == project_root or data_dir.is_relative_to(project_root):
        user_state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
        project_key = hashlib.sha256(str(project_root).encode()).hexdigest()
        return user_state / "julius" / "managed-config" / project_key
    return data_dir / "managed-config"


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


def _stored_task_prices(
    data_dir: Path, events: list[dict], baseline: dict | None,
) -> dict[str, dict]:
    """Resolve only explicitly linked historical USD snapshots for this task."""
    references: dict[str, tuple[str, str]] = {}

    def add(snapshot_id: object, provider_id: object, model_id: object) -> None:
        if not all(isinstance(item, str) and item for item in (
            snapshot_id, provider_id, model_id,
        )):
            return
        assert isinstance(snapshot_id, str)
        assert isinstance(provider_id, str)
        assert isinstance(model_id, str)
        identity = (provider_id, model_id)
        if snapshot_id in references and references[snapshot_id] != identity:
            raise ValueError("Price snapshot ID has conflicting model identities")
        references[snapshot_id] = identity

    for event in events:
        if event.get("eventType") == "usage":
            add(event["payload"].get("priceSnapshotId"),
                event.get("providerId"), event.get("modelId"))
    if baseline is not None and isinstance(baseline.get("calls"), list):
        for call in baseline["calls"]:
            if isinstance(call, dict):
                add(call.get("priceSnapshotId"), call.get("providerId"), call.get("modelId"))
    path = data_dir / "prices.sqlite3"
    if not references or not path.exists():
        return {}
    with PriceStore(path) as store:
        resolved = {
            snapshot_id: store.pricing_snapshot(
                snapshot_id, provider_id=provider_id, model_id=model_id,
            )
            for snapshot_id, (provider_id, model_id) in references.items()
        }
    return {snapshot_id: snapshot for snapshot_id, snapshot in resolved.items()
            if snapshot is not None}


def run(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    command = args.command
    argument = args.arguments[0] if args.arguments else None
    if not command:
        parser.print_help()
        return 0
    if args.include_raw and (command != "export" or args.format != "events-jsonl"):
        raise ValueError("--include-raw requires export --format events-jsonl")
    if command == "probe":
        if args.arguments != ["codex"]:
            raise ValueError("Use probe codex --project <id> [--task <id>]")
        project_id = _required(args.project, "--project")
        probe_result = probe_codex_usage(confirmed=True)
        usage = probe_result["usage"]
        input_tokens = usage["inputTokens"] if usage is not None else None
        output_tokens = usage["outputTokens"] if usage is not None else None
        cache_read_tokens = usage["cachedInputTokens"] if usage is not None else None
        complete = bool(
            probe_result["status"] == "complete"
            and input_tokens is not None
            and output_tokens is not None
        )
        event_id = str(uuid4())
        thread_id = usage["threadId"] if usage is not None else None
        event = {
            "schemaVersion": 1,
            "eventId": event_id,
            "occurredAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "sourceId": "julius-codex-probe",
            "sourceEventId": event_id,
            "projectId": project_id,
            "taskId": args.task,
            "sessionId": thread_id or event_id,
            "requestId": None,
            "attemptId": None,
            "clientId": "codex-cli",
            "adapterVersion": "codex-cli-jsonl-1",
            "modelId": None,
            "providerId": None,
            "executionLocation": "unknown",
            "eventType": "usage",
            "evidence": "runtime_reported",
            "payload": {
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
                "cacheReadTokens": cache_read_tokens,
                "cacheWriteTokens": None,
                "complete": complete,
                "category": "primary",
                "callId": None,
                "costUsd": None,
                "observationScope": "session_delta",
                "rawUsage": {
                    "probeStatus": probe_result["status"],
                    "reasoningOutputTokens": usage["reasoningOutputTokens"] if usage is not None else None,
                    "turnCompleted": usage["turnCompleted"] if usage is not None else False,
                    "failed": usage["failed"] if usage is not None else None,
                },
                "normalizerVersion": "codex-cli-jsonl-1",
            },
        }
        with Julius(Path(args.data_dir).absolute()) as julius:
            receipt = julius.record_usage(event)
        _json({"result": probe_result, "usageEvent": event, "usageReceipt": receipt})
        return 0 if complete else 2
    if command == "doctor":
        _json(doctor())
        return 0
    if command == "mcp":
        if args.arguments != ["recovery"]:
            raise ValueError("Use mcp recovery --project <id>")
        root = Path(args.data_dir).absolute() / "artifacts"
        project_id = _required(args.project, "--project")
        if args.project_root:
            memory = MemoryStore(Path(args.data_dir).absolute() / "memory.sqlite3")
            try:
                serve_recovery_stdio(
                    ArtifactStore(root), project_id, symbol_memory=memory,
                    project_root=args.project_root,
                )
            finally:
                memory.close()
        else:
            serve_recovery_stdio(ArtifactStore(root), project_id)
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
        if argument == "list":
            _json(
                discover_lmstudio(args.endpoint or "http://127.0.0.1:1234")
                if args.runtime == "lmstudio"
                else discover_ollama(args.endpoint or "http://127.0.0.1:11434")
            )
        elif argument in ("record", "history", "scan"):
            directory = Path(args.data_dir).absolute()
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            with ModelRegistry(directory / "models.sqlite3") as registry:
                if argument == "record":
                    snapshot = ModelSnapshot.model_validate(
                        _json_file(_required(args.state_file, "--state-file"))
                    )
                    _json(registry.add(snapshot))
                elif argument == "history":
                    _json(registry.history(
                        endpoint=_required(args.endpoint, "--endpoint"),
                        requested_model=_required(args.model, "--model"),
                    ))
                else:
                    default_endpoint = (
                        "http://127.0.0.1:1234" if args.runtime == "lmstudio"
                        else "http://127.0.0.1:11434"
                    )
                    _json(scan_models(
                        registry, provider=args.runtime,
                        endpoint=args.endpoint or default_endpoint,
                    ))
        else:
            raise ValueError("Use models list, record, history, or scan")
        return 0
    if command == "symbols":
        if len(args.arguments) != 2 or argument not in ("index", "search", "invalidate"):
            raise ValueError("Use symbols index|search|invalidate <relative-file-or-query> --project <id> --project-root <directory> --snapshot <id>")
        directory = Path(args.data_dir).absolute()
        memory = MemoryStore(directory / "memory.sqlite3")
        try:
            symbols = SymbolStore(
                memory, project_id=_required(args.project, "--project"),
                project_root=_required(args.project_root, "--project-root"),
            )
            try:
                target = args.arguments[1]
                symbol_snapshot = _required(args.snapshot, "--snapshot")
                if argument == "index":
                    _json(symbols.index_file(target, snapshot=symbol_snapshot))
                elif argument == "search":
                    _json(symbols.search(target, snapshot=symbol_snapshot))
                else:
                    _json({"removed": symbols.invalidate_file(target, snapshot=symbol_snapshot)})
            finally:
                symbols.close()
        finally:
            memory.close()
        return 0
    if command == "prices":
        if args.arguments not in (["record"], ["history"], ["lookup"]):
            raise ValueError("Use prices record, history, or lookup")
        if argument == "record":
            price_snapshot = PriceSnapshot.model_validate_json(
                _read(_required(args.state_file, "--state-file"), 1_000_000)
            )
        else:
            price_endpoint = _required(args.endpoint, "--endpoint")
            price_provider = _required(args.provider, "--provider")
            price_model = _required(args.model, "--model")
            if argument == "lookup":
                price_currency = _required(args.currency, "--currency")
                price_tier = _required(args.tier, "--tier")
                price_cache_regime = _required(args.cache_regime, "--cache-regime")
                price_at = datetime.fromisoformat(_required(args.at, "--at").replace("Z", "+00:00"))
        directory = Path(args.data_dir).absolute()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        with PriceStore(directory / "prices.sqlite3") as price_store:
            if argument == "record":
                _json(price_store.record(price_snapshot))
            elif argument == "history":
                _json(price_store.history(
                    endpoint=price_endpoint, provider=price_provider, model=price_model,
                ))
            else:
                _json(price_store.lookup(
                    endpoint=price_endpoint, provider=price_provider, model=price_model,
                    currency=price_currency, tier=price_tier,
                    cache_regime=price_cache_regime, at=price_at,
                ))
        return 0
    if command == "evaluate":
        if args.arguments != ["replay"]:
            raise ValueError("Use evaluate replay --state-file <json>")
        payload = _json_file(_required(args.state_file, "--state-file"), 16 * 1024 * 1024)
        if not isinstance(payload, dict):
            raise ValueError("Evaluation input must be a JSON object")
        fixtures = payload.get("fixtures")
        attempts = payload.get("attempts")
        if not isinstance(fixtures, list) or not isinstance(attempts, list):
            raise ValueError("Evaluation requires fixtures and attempts arrays")
        _json(replay_paired_fixtures(
            [FrozenFixture.model_validate(item) for item in fixtures],
            [Attempt.model_validate(item) for item in attempts],
            baseline_arm=_required(payload.get("baselineArm"), "baselineArm"),
            candidate_arm=_required(payload.get("candidateArm"), "candidateArm"),
            seed=payload.get("seed", 0),
        ))
        return 0
    if command == "policy":
        if args.arguments not in (["check"], ["record"], ["status"]):
            raise ValueError("Use policy check, record, or status --state-file <json>")
        payload = _json_file(_required(args.state_file, "--state-file"))
        if not isinstance(payload, dict):
            raise ValueError("Policy input must be a JSON object")
        scope = Scope.model_validate(payload.get("scope"))
        policy = GuardPolicy.model_validate(payload.get("policy"))
        if args.arguments == ["record"]:
            kind = payload.get("recordType")
            record_data = payload.get("record")
            record: TaskOutcome | ManualAction
            if kind == "outcome":
                record = TaskOutcome.model_validate(record_data)
            elif kind == "manual":
                record = ManualAction.model_validate(record_data)
            else:
                raise ValueError("Policy recordType must be outcome or manual")
            if record.scope != scope:
                raise ValueError("Policy record scope mismatch")
            directory = Path(args.data_dir).absolute()
            with QualityStore(directory / "quality.sqlite") as store:
                _json(store.append(record, policy))
            return 0
        if args.arguments == ["status"]:
            directory = Path(args.data_dir).absolute()
            with QualityStore(directory / "quality.sqlite") as store:
                _json(store.decision(scope, policy))
            return 0
        outcomes = payload.get("outcomes")
        actions = payload.get("actions", [])
        if not isinstance(outcomes, list) or not isinstance(actions, list):
            raise ValueError("Policy check requires outcomes and actions arrays")
        _json(decide_suspension(
            scope, policy,
            [TaskOutcome.model_validate(item) for item in outcomes],
            [ManualAction.model_validate(item) for item in actions],
        ))
        return 0
    if command == "run" and args.agent not in ("grok", "xai", "claude"):
        raise ValueError("Run requires --agent grok or --agent claude")
    if command == "run" and args.agent == "claude":
        if args.arguments or args.request or args.restore_loop:
            raise ValueError("Claude runner does not accept request files or positional arguments")
        if args.prompt_file:
            if args.profile != "observe" or args.recovery_verified:
                raise ValueError("Bounded Claude print mode currently supports observe profile only")
            if args.max_budget_usd is None:
                raise ValueError("Claude print mode requires --max-budget-usd")
            prompt = _read(args.prompt_file, 32 * 1024)
            result = run_claude_print(
                prompt=prompt,
                project_id=_required(args.project, "--project"),
                task_id=args.task,
                data_dir=Path(args.data_dir).absolute(),
                model=args.model,
                max_turns=args.max_turns,
                max_budget_usd=args.max_budget_usd,
                timeout_seconds=args.timeout_seconds if args.timeout_seconds is not None else 90.0,
            )
            usage = result["usage"]
            input_parts = (
                usage["input_tokens"], usage["cache_read_input_tokens"],
                usage["cache_creation_input_tokens"],
            )
            input_total = sum(input_parts) if all(part is not None for part in input_parts) else None
            event_id = str(uuid4())
            known_model = result["actual_model"]
            cost = result["cost_usd"] if known_model is not None else None
            event = {
                "schemaVersion": 1, "eventId": event_id,
                "occurredAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "sourceId": "julius-claude-print", "sourceEventId": event_id,
                "projectId": _required(args.project, "--project"),
                "taskId": args.task, "sessionId": result["session_id"] or str(uuid4()),
                "requestId": None, "attemptId": None,
                "clientId": "claude-code", "adapterVersion": "0.1.0-experimental",
                "modelId": known_model, "providerId": "anthropic",
                "executionLocation": "remote", "eventType": "usage",
                "evidence": "runtime_reported",
                "payload": {
                    "inputTokens": input_total,
                    "outputTokens": usage["output_tokens"],
                    "cacheReadTokens": usage["cache_read_input_tokens"],
                    "cacheWriteTokens": usage["cache_creation_input_tokens"],
                    "complete": bool(result["complete"] and input_total is not None
                                     and usage["output_tokens"] is not None),
                    "category": "primary", "callId": None,
                    "costUsd": cost,
                    "costProvenance": {
                        "estimateSource": "client_result",
                        "estimateField": "total_cost_usd",
                        "estimateScope": "session_delta",
                        "estimateClientId": "claude-code",
                    } if cost is not None else None,
                    "observationScope": "session_delta",
                    "rawUsage": usage,
                    "normalizerVersion": "claude-print-final-1",
                },
            }
            with Julius(Path(args.data_dir).absolute()) as julius:
                receipt = julius.record_usage(event)
            _json({"result": result, "usageEvent": event, "usageReceipt": receipt})
            return 0 if result["complete"] else 2
        if args.profile == "safe" and not args.recovery_verified:
            raise ValueError("Claude safe profile requires --recovery-verified after checking session recovery")
        return run_claude(
            project_id=_required(args.project, "--project"),
            data_dir=Path(args.data_dir).absolute(),
            task_id=args.task,
            enable_safe_hook=args.profile == "safe",
            recovery_verified=args.recovery_verified,
        )
    if command == "integrations":
        if args.arguments != ["remove", "claude"]:
            raise ValueError("Use integrations remove claude --project-root <directory>")
        manager = ClaudeIntegrationManager(
            _required(args.project_root, "--project-root"),
            _integration_state_root(
                Path(args.data_dir).absolute(), Path(args.project_root).absolute()
            ),
        )
        _json({"removed": manager.remove(), "integration": "claude"})
        return 0
    if command == "jev" and argument != "shadow":
        raise ValueError("Use jev shadow --state-file <json> --project <id> --post-call-threshold-usd <amount>")
    directory = Path(args.data_dir).absolute()
    if command == "setup" and args.project_root:
        if args.arguments:
            raise ValueError("Setup does not accept positional arguments")
        if args.profile == "safe" and not args.recovery_verified:
            raise ValueError("Persistent safe hook requires --recovery-verified")
        project_root = Path(args.project_root).resolve()
        project_id = _required(args.project, "--project")
        detected = doctor()
        module_command = [sys.executable, "-m", "julius.cli", "--data-dir", str(directory)]
        hook_command = shlex.join([
            *module_command, "hook", "claude-post-tool-use", "--project", project_id,
            "--profile", args.profile,
            *(["--recovery-available"] if args.recovery_verified else []),
        ])
        manager = ClaudeIntegrationManager(
            project_root, _integration_state_root(directory, project_root),
        )
        plan = manager.preview(
            hook_command=hook_command,
            mcp_command=sys.executable,
            mcp_args=["-m", "julius.cli", "--data-dir", str(directory),
                      "mcp", "recovery", "--project", project_id],
            recovery_verified=args.recovery_verified,
        )
        digest = hashlib.sha256(
            plan.settings.desired + b"\0" + plan.mcp.desired
        ).hexdigest()
        if args.apply_plan is not None:
            if args.apply_plan != digest:
                raise ValueError("Setup plan changed; preview again before applying")
            applied = manager.apply(plan)
        else:
            applied = False
        _json({
            "integration": "claude", "projectRoot": str(project_root),
            "planHash": digest, "applied": applied,
            "hookProfile": args.profile,
            "recoveryAttested": args.recovery_verified,
            "backupState": str(_integration_state_root(directory, project_root)),
            "settingsDiff": plan.settings.diff, "mcpDiff": plan.mcp.diff,
            "doctor": detected,
        })
        return 0
    if command == "setup" and args.apply_plan is not None:
        raise ValueError("--apply-plan requires --project-root")
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
            quality_scope = None
            quality_policy = None
            if args.guard_file:
                _required(args.model, "--model with --guard-file")
                guard_data = _json_file(args.guard_file)
                if not isinstance(guard_data, dict):
                    raise ValueError("Guard file must be a JSON object")
                quality_scope = Scope.model_validate(guard_data.get("scope"))
                quality_policy = GuardPolicy.model_validate(guard_data.get("policy"))
            _json(
                julius.optimize(
                    {
                        "projectId": _required(args.project, "--project"),
                        "modelId": args.model,
                        "content": content,
                        "category": "tool_output",
                    },
                    {"mode": args.profile, "version": "1.0.0", "approved": args.profile == "safe"},
                    quality_scope=quality_scope, quality_policy=quality_policy,
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
            if command == "export" and args.format == "events-jsonl":
                for event in julius.ledger.export_history(filters):
                    exported = event
                    if not args.include_raw and event["eventType"] == "usage":
                        exported = {**event, "payload": {**event["payload"], "rawUsage": None}}
                    print(json.dumps(exported, ensure_ascii=False, allow_nan=False,
                                     separators=(",", ":")))
                return 0
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
                task_events = julius.ledger.events(filters)
                if prices is None:
                    prices = _stored_task_prices(directory, task_events, baseline)
                analysis = analyze_task(
                    task_events, baseline=baseline, prices=prices,
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
                    handle.write(render_html({**data, "groupBy": args.by or "model"}))
                print(f"Local HTML report written to {destination}")
            elif command == "export":
                if args.format == "json":
                    _json(data)
                elif args.format in (None, "csv"):
                    print(render_csv(data), end="")
                else:
                    raise ValueError("Export --format must be csv, json, or events-jsonl")
            elif args.json:
                _json(data)
            else:
                print(render_text(data))
    return 0


def main() -> None:
    try:
        raise SystemExit(run())
    except (ValueError, OSError, RuntimeError, KeyError, TypeError, sqlite3.Error,
            ValidationError) as error:
        print(f"Julius: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
