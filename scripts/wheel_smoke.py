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
                [str(python), *args], cwd=root, env=env, capture_output=True, text=True, check=True
            )
            return completed.stdout

        location = run("-c", "import julius, julius._native; print(julius.__file__)").strip()
        assert str(environment) in location, "Source tree leaked into isolated wheel smoke"
        assert run(
            "-c",
            "from julius.xai import XAIAdapter; from julius.jev import shadow_decide; "
            "from julius.economics import analyze_task; "
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
        print(
            "Isolated wheel smoke passed: native and optional module imports, idempotency, 7,000 marginal reduction, unknown money, optimize/restore, HTML/CSV."
        )


if __name__ == "__main__":
    main()
