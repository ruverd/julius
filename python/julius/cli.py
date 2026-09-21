"""Local command interface. Reports never call a model."""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from . import __version__
from .events import validate_event
from .importers import import_claude_transcript, import_codex_rollout
from .models import discover_ollama, doctor
from .query import query_window
from .reporting import render_csv, render_html, render_text, report
from .sdk import Julius


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Julius: local evidence-aware context tools. No hidden model calls."
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
        ],
    )
    parser.add_argument("arguments", nargs="*")
    parser.add_argument("--data-dir", default=os.environ.get("JULIUS_HOME", ".julius"))
    parser.add_argument(
        "--since", default="7d", help="Rolling days/hours/minutes or ISO time; inclusive start"
    )
    parser.add_argument("--until", help="Exclusive end; local dates convert to UTC")
    for option in ("project", "task", "model", "source", "endpoint", "output"):
        parser.add_argument(f"--{option}")
    parser.add_argument("--by", choices=["model", "category", "client"])
    parser.add_argument("--format")
    parser.add_argument("--profile", choices=["observe", "safe"], default="observe")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--explain", action="store_true")
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
    if command == "models":
        if argument != "list":
            raise ValueError("Use models list")
        _json(discover_ollama(args.endpoint or "http://127.0.0.1:11434"))
        return 0
    if command == "run":
        raise ValueError(
            "Native execution is not integrated. Use the SDK in an authorized harness."
        )
    if command == "integrations":
        if argument != "remove":
            raise ValueError("Use integrations remove <id>")
        print("No managed integrations exist. No client configuration was changed.")
        return 0
    directory = Path(args.data_dir).absolute()
    with Julius(directory) as julius:
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
