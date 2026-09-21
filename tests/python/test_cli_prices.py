"""Offline price-store commands preserve dated source evidence."""

import json
import os
from pathlib import Path
import subprocess
import sys


def _cli(tmp_path: Path, *args: str, success: bool = True) -> object:
    process = subprocess.run(
        [sys.executable, "-m", "julius", *args, "--data-dir", str(tmp_path / "data")],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
    )
    assert (process.returncode == 0) is success, process.stderr
    return json.loads(process.stdout) if success else process.stderr


def _snapshot(tmp_path: Path, name: str, **changes: object) -> Path:
    value = {
        "endpoint": "https://api.example.test/v1",
        "provider": "example",
        "model": "model-a",
        "currency": "USD",
        "tier": "standard",
        "cache_regime": "default",
        "source": "provider-price-page",
        "source_date": "2026-08-20",
        "effective_at": "2026-09-01T00:00:00Z",
        "expires_at": "2026-10-01T00:00:00Z",
        "rates_per_million": {
            "inputUncached": "1.25", "cacheRead": None,
            "cacheWrite": None, "output": "4.50",
        },
    }
    value.update(changes)
    path = tmp_path / name
    path.write_text(json.dumps(value))
    return path


def _identity() -> tuple[str, ...]:
    return ("--endpoint", "https://api.example.test/v1", "--provider", "example",
            "--model", "model-a")


def _lookup(tmp_path: Path, at: str = "2026-09-15T00:00:00Z") -> dict:
    result = _cli(tmp_path, "prices", "lookup", *_identity(), "--currency", "USD",
                  "--tier", "standard", "--cache-regime", "default", "--at", at)
    assert isinstance(result, dict)
    return result


def test_cli_price_history_and_dated_lookup(tmp_path: Path) -> None:
    assert _lookup(tmp_path)["status"] == "unknown"
    source = _snapshot(tmp_path, "price.json")
    recorded = _cli(tmp_path, "prices", "record", "--state-file", str(source))
    assert isinstance(recorded, dict)
    assert recorded["rates_per_million"]["cacheRead"] is None
    assert recorded["source_date"] == "2026-08-20"
    history = _cli(tmp_path, "prices", "history", *_identity())
    assert history == [recorded]
    assert _lookup(tmp_path) == {
        "status": "known", "snapshot": recorded,
        "candidateIds": [recorded["snapshotId"]],
    }
    assert _lookup(tmp_path, "2026-10-01T00:00:00Z")["status"] == "unknown"
    assert _lookup(tmp_path, "2026-08-31T23:59:59Z")["status"] == "unknown"


def test_cli_overlapping_prices_remain_ambiguous(tmp_path: Path) -> None:
    first = _cli(tmp_path, "prices", "record", "--state-file",
                 str(_snapshot(tmp_path, "first.json")))
    second = _cli(tmp_path, "prices", "record", "--state-file",
                  str(_snapshot(tmp_path, "second.json", source="contract")))
    assert isinstance(first, dict) and isinstance(second, dict)
    result = _lookup(tmp_path)
    assert result == {
        "status": "ambiguous", "snapshot": None,
        "candidateIds": [first["snapshotId"], second["snapshotId"]],
    }


def test_cli_price_input_validation(tmp_path: Path) -> None:
    source = _snapshot(tmp_path, "invalid.json", rates_per_million={"output": "1"})
    error = _cli(tmp_path, "prices", "record", "--state-file", str(source), success=False)
    assert "All four rate categories are required" in error
    assert not (tmp_path / "data").exists()
    error = _cli(tmp_path, "prices", "lookup", *_identity(), "--currency", "USD",
                 "--tier", "standard", "--cache-regime", "default",
                 "--at", "2026-09-15", success=False)
    assert "Lookup time needs timezone" in error
    error = _cli(tmp_path, "prices", "history", "--model", "model-a", success=False)
    assert "Missing --endpoint" in error
