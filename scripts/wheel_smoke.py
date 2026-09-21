"""Install a built wheel into a clean environment and exercise the offline CLI."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    wheel = Path(sys.argv[1]).resolve()
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/events.jsonl"
    with tempfile.TemporaryDirectory(prefix="julius-wheel-") as temporary:
        root = Path(temporary)
        environment = root / "environment"
        subprocess.run(["uv", "venv", "--python", sys.executable, str(environment)], check=True)
        python = environment / "bin/python"
        subprocess.run(["uv", "pip", "install", "--python", str(python), str(wheel)], check=True)
        env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        env["JULIUS_HOME"] = str(root / "data")

        def run(*args: str) -> str:
            completed = subprocess.run(
                [str(python), *args], cwd=root, env=env, capture_output=True, text=True
            )
            if completed.returncode:
                raise RuntimeError(f"Wheel smoke command failed: {args}: {completed.stderr}")
            return completed.stdout

        location = run("-c", "import julius, julius._native; print(julius.__file__)").strip()
        assert str(environment) in location, "Source tree leaked into isolated wheel smoke"
        assert run(
            "-c",
            "from julius.xai import XAIAdapter; from julius.jev import shadow_decide; "
            "from julius.economics import analyze_task; from julius.evaluation import analyze_paired_trials; "
            "from julius.stdio_api import serve_stdio; "
            "from julius.claude_runner import build_launch_plan; "
            "from julius.lmstudio import discover_lmstudio; "
            "from julius.xai_optimization import prepare_optimized_request; "
            "from julius.xai_tool_loop import run_restore_loop; "
            "from julius.claude_probe import probe_local_protocol; "
            "from julius.claude_config import plan_claude_project_config; "
            "from julius.integration_manager import ClaudeIntegrationManager; "
            "from julius.model_registry import ModelRegistry; "
            "from julius.evaluation_runner import replay_paired_fixtures; "
            "from julius.model_scan import scan_models; "
            "from julius.quality_guard import decide_suspension; "
            "from julius.quality_store import QualityStore; "
            "from julius.request_measurement import measure_request_pair; "
            "from julius.price_store import PriceStore; "
            "from julius.claude_print_runner import run_claude_print; "
            "from julius.claude_pilot import run_claude_pilot; "
            "from julius.claude_pilot_analysis import analyze_claude_pilot_report; "
            "from julius.codex_live_probe import probe_codex_usage; "
            "print(XAIAdapter().prepare({'model':'grok-fixture','input':'hi'}).decode())",
        ).strip() == '{"model":"grok-fixture","input":"hi"}'
        assert "0.2.0" in run("-m", "julius", "--version")
        assert json.loads(run("-m", "julius", "import", str(fixture)))["imported"] == 3
        assert json.loads(run("-m", "julius", "import", str(fixture)))["duplicates"] == 3
        window = ("--since", "2026-09-21T00:00:00Z", "--until", "2026-09-22T00:00:00Z")
        report = json.loads(run("-m", "julius", "savings", *window, "--json"))
        assert report["directInputReduction"][0]["tokens"]["total"] == 7000
        assert report["financialSavingsUsd"] is None
        source = root / "tool.txt"
        source.write_text(("neutral log text " + "x" * 240 + "\n") * 4)
        optimized = json.loads(
            run("-m", "julius", "optimize", str(source), "--project", "demo", "--profile", "safe")
        )
        assert optimized["receipt"]["applied"] is True
        reference = optimized["original"]["id"]
        assert run("-m", "julius", "restore", reference, "--project", "demo") == source.read_text()
        run("-m", "julius", "dashboard", *window, "--output", str(root / "report.html"))
        assert "group" in run("-m", "julius", "export", *window, "--format", "csv")
        model_file = root / "model.json"
        model_file.write_text(json.dumps({
            "endpoint": "http://127.0.0.1:11434", "provider": "ollama",
            "requested_model": "fixture", "state": "unknown", "source": "wheel-smoke",
        }))
        assert json.loads(run("-m", "julius", "models", "record", "--state-file", str(model_file)))["state"] == "unknown"
        assert len(json.loads(run(
            "-m", "julius", "models", "history", "--endpoint", "http://127.0.0.1:11434",
            "--model", "fixture",
        ))) == 1
        project = root / "project"
        (project / ".claude").mkdir(parents=True)
        preview = json.loads(run(
            "-m", "julius", "setup", "--project-root", str(project), "--project", "fixture",
        ))
        assert preview["applied"] is False
        applied = json.loads(run(
            "-m", "julius", "setup", "--project-root", str(project), "--project", "fixture",
            "--apply-plan", preview["planHash"],
        ))
        assert applied["applied"] is True
        assert json.loads(run(
            "-m", "julius", "integrations", "remove", "claude", "--project-root", str(project),
        ))["removed"] is True
        print(
            "Isolated wheel smoke passed: native and optional imports, event idempotency, "
            "7,000 marginal reduction, unknown money, optimize/restore, HTML/CSV, model snapshots, "
            "and reversible Claude setup."
        )


if __name__ == "__main__":
    main()
