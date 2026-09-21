"""Run the preregistered synthetic Jev shadow pilot only on explicit request."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

from julius.jev_live_pilot import run_pilot
from julius.sdk import Julius


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Make up to five TypeSafe API calls")
    parser.add_argument("--journal-dir", type=Path, required=True,
                        help="New directory for pre-call manifest, attempts, and captures")
    parser.add_argument("--data-dir", type=Path, required=True,
                        help="Local Julius ledger directory")
    parser.add_argument("--input-usd-per-million", type=float, required=True,
                        help="Caller-supplied price for pinned jev-1.13.0")
    parser.add_argument("--max-input-tokens-per-call", type=int, required=True,
                        help="Assumed upper bound; not a provider-enforced spending cap")
    parser.add_argument("--total-budget-usd", type=float, required=True,
                        help="Reject before sending if modeled maximum exceeds this amount")
    parser.add_argument("--price-source", required=True)
    parser.add_argument("--price-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required for external model calls")
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        parser.error("TYPESAFE_API_KEY is required")
    with Julius(args.data_dir.absolute()) as julius:
        result = run_pilot(
            journal_dir=args.journal_dir.absolute(), julius=julius, api_key=key,
            input_usd_per_million=args.input_usd_per_million,
            max_input_tokens_per_call=args.max_input_tokens_per_call,
            total_budget_usd=args.total_budget_usd,
            project_id="jev-shadow-pilot", session_id=str(uuid4()),
            price_source=args.price_source, price_date=args.price_date,
            timeout_seconds=args.timeout_seconds,
        )
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
