"""Explicit, read-only local discovery persisted as historical snapshots."""

from __future__ import annotations

from typing import Any, Literal

from .lmstudio import discover_lmstudio
from .model_registry import ModelRegistry, ModelSnapshot, ModelState
from .models import discover_ollama


Provider = Literal["ollama", "lmstudio"]


def scan_models(
    registry: ModelRegistry,
    *,
    provider: Provider,
    endpoint: str,
    api_token: str | None = None,
) -> dict[str, Any]:
    """Run one authorized loopback discovery and append its observed model facts."""
    if provider == "ollama":
        if api_token is not None:
            raise ValueError("Ollama discovery does not accept an API token")
        discovered = discover_ollama(endpoint)
        source = "ollama-local-discovery"
    elif provider == "lmstudio":
        discovered = discover_lmstudio(endpoint, api_token=api_token)
        source = "lmstudio-local-discovery"
    else:
        raise ValueError("Unsupported local model provider")
    origin = discovered["endpoint"]
    records: list[dict[str, object]] = []
    for item in discovered["models"]:
        loaded = item.get("loaded")
        state: ModelState = "loaded" if loaded is True else "installed"
        name = item["name"]
        snapshot = ModelSnapshot(
            endpoint=origin,
            provider=provider,
            requested_model=name,
            responded_model=None,
            alias=None,
            digest=item.get("digest"),
            quantization=item.get("quantization"),
            tokenizer=None,
            template=None,
            context_window=None,
            tool_capabilities={},
            state=state,
            source=source,
            source_updated_at=None,
        )
        records.append(registry.add(snapshot))
    return {"provider": provider, "endpoint": origin, "snapshots": records,
            "error": discovered.get("error")}
