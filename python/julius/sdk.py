"""Versioned local harness interface with no hidden model execution."""

from pathlib import Path

from .artifacts import ArtifactStore
from .events import validate_event
from .ledger import Ledger
from .optimizer import optimize
from .query import query_window
from .reporting import report


class Julius:
    def __init__(self, directory: str | Path):
        directory = Path(directory)
        self.artifacts = ArtifactStore(directory / "artifacts")
        self.ledger = Ledger(directory / "ledger.sqlite")

    def optimize(self, context: dict, policy: dict) -> dict:
        eligibility = optimize({**context, "recovery": None}, policy)
        if eligibility["receipt"]["reason"] != "recovery_required":
            return {**eligibility, "original": None}
        original = self.artifacts.put(context["projectId"], context["content"])
        try:
            result = optimize(
                {**context, "recovery": {"artifactId": original["id"], "available": True}}, policy
            )
        except Exception:
            self.artifacts.delete(context["projectId"], original["id"])
            raise
        if not result["receipt"]["applied"]:
            self.artifacts.delete(context["projectId"], original["id"])
            return {**result, "original": None}
        return {**result, "original": original}

    def record_usage(self, event: dict) -> dict:
        event = validate_event(event)
        if event["eventType"] != "usage":
            raise ValueError("record_usage requires a usage event")
        return self.ledger.record(event)

    def record_outcome(self, event: dict) -> dict:
        event = validate_event(event)
        if event["eventType"] != "outcome":
            raise ValueError("record_outcome requires an outcome event")
        return self.ledger.record(event)

    def report(self, query: dict | None = None) -> dict:
        query = query or {}
        window = query_window(query)
        return report(
            self.ledger.events({**query, "since": window["since"], "until": window["until"]}),
            window,
        )

    def close(self) -> None:
        self.ledger.close()

    def __enter__(self) -> "Julius":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
