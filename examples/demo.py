"""Synthetic ledger example, never a provider measurement or benchmark."""

import json
import os
from pathlib import Path

from julius.sdk import Julius

fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/events.jsonl"
with Julius(os.environ.get("JULIUS_HOME", ".julius-demo")) as julius:
    julius.ledger.record_many([json.loads(line) for line in fixture.read_text().splitlines()])
    print(
        json.dumps(
            julius.report({"since": "2026-09-21T00:00:00Z", "until": "2026-09-22T00:00:00Z"}),
            indent=2,
        )
    )
