"""Read-only discovery through LM Studio's local native v1 model list."""

from __future__ import annotations

import ipaddress
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


MAX_RESPONSE_BYTES = 1_048_576
MAX_MODELS = 1_000


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, request: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        raise URLError("LM Studio redirect blocked")


def _origin(endpoint: str) -> str:
    if not isinstance(endpoint, str):
        raise ValueError("LM Studio endpoint must be a loopback HTTP URL")
    parsed = urlsplit(endpoint)
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError as error:
        raise ValueError("LM Studio endpoint must use a literal loopback IP") from error
    if (
        parsed.scheme != "http"
        or not address.is_loopback
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("LM Studio endpoint must be a loopback HTTP origin with a port")
    return f"http://[{address}]:{port}" if address.version == 6 else f"http://{address}:{port}"


def _model(item: dict[str, Any], origin: str) -> dict[str, Any] | None:
    key = item.get("key")
    if not isinstance(key, str) or not key:
        return None
    instances = item.get("loaded_instances")
    loaded = bool(instances) if isinstance(instances, list) else None
    quantization = item.get("quantization")
    quant = (
        quantization.get("name")
        if isinstance(quantization, dict) and isinstance(quantization.get("name"), str)
        else None
    )
    variant = item.get("selected_variant")
    variant = variant if isinstance(variant, str) and variant else None
    return {
        "id": f"{origin}|{key}|{variant or 'unknown'}|{quant or 'unknown'}",
        "name": key,
        "type": item.get("type") if item.get("type") in ("llm", "embedding") else None,
        "displayName": item.get("display_name") if isinstance(item.get("display_name"), str) else None,
        "installed": True,
        "loaded": loaded,
        "quantization": quant,
        "selectedVariant": variant,
        "digest": None,
    }


def discover_lmstudio(
    endpoint: str = "http://127.0.0.1:1234", *, api_token: str | None = None
) -> dict[str, Any]:
    """List locally available models without causing load, download, or inference."""
    try:
        origin = _origin(endpoint)
    except ValueError as error:
        return {"endpoint": endpoint, "models": [], "error": str(error)}
    if api_token is not None and (
        not isinstance(api_token, str) or not api_token or "\r" in api_token or "\n" in api_token
    ):
        return {"endpoint": origin, "models": [], "error": "Invalid LM Studio API token"}
    headers = {"Accept": "application/json"}
    if api_token is not None:
        headers["Authorization"] = f"Bearer {api_token}"
    try:
        opener = build_opener(ProxyHandler({}), _NoRedirect)
        request = Request(f"{origin}/api/v1/models", headers=headers, method="GET")
        with opener.open(request, timeout=2) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("LM Studio model list exceeds 1 MiB")
        body = json.loads(raw)
        if not isinstance(body, dict) or not isinstance(body.get("models"), list):
            raise ValueError("Invalid LM Studio model list")
        items = body["models"]
        if len(items) > MAX_MODELS or any(not isinstance(item, dict) for item in items):
            raise ValueError("Invalid LM Studio model list")
    except (OSError, ValueError, HTTPError, URLError, UnicodeError) as error:
        return {"endpoint": origin, "models": [], "error": str(error)}
    models = [model for item in items if (model := _model(item, origin)) is not None]
    return {"endpoint": origin, "models": models, "error": None}
