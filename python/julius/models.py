"""Read-only local runtime discovery without credentials or configuration access."""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


_CAPABILITIES = {
    "canObserveUsage": False,
    "canOptimizeInput": False,
    "canImportUsage": False,
    "liveCompatibilityTested": False,
}

# Exact CLI versions observed locally. This is not a live integration certification.
_CLIENT_MATRIX = {
    "claude": {"2.1.278": "2.1.278 (Claude Code)"},
    "codex": {"0.154.0": "codex-cli 0.154.0"},
}


def _client_capability(name: str, version: str | None) -> tuple[str, dict[str, str]]:
    features = {
        "versionDiscovery": "unsupported",
        "manualUsageImport": "unsupported",
        "liveUsageObservation": "unsupported",
        "inputOptimization": "unsupported",
    }
    if version is None:
        return "unsupported", features
    features["versionDiscovery"] = "observe_only"
    match = re.search(r"(?<![\d.])(\d+\.\d+\.\d+)(?![\d.])", version)
    if match and _CLIENT_MATRIX[name].get(match.group(1)) == version:
        features["manualUsageImport"] = "experimental"
    return ("experimental" if features["manualUsageImport"] == "experimental" else "unsupported"), features


def doctor() -> dict[str, Any]:
    clients = []
    for name in ("claude", "codex"):
        installed, version, detail = False, None, "Executable unavailable"
        try:
            result = subprocess.run(
                [name, "--version"], capture_output=True, text=True, timeout=2, check=False
            )
            version_line = (result.stdout or result.stderr).strip().splitlines()
            if result.returncode == 0 and version_line:
                installed, version = True, version_line[0][:200]
                detail = "Executable detected; no live integration capability verified"
            else:
                detail = "Version probe failed"
        except (OSError, subprocess.TimeoutExpired):
            pass
        capability, feature_status = _client_capability(name, version)
        clients.append(
            {
                "name": name,
                "executable": name,
                "installed": installed,
                "version": version,
                "capability": capability,
                "capabilities": dict(_CAPABILITIES),
                "featureStatus": feature_status,
                "detail": detail,
            }
        )
    return {"clients": clients}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, request: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        raise URLError("Ollama redirect blocked")


def _entries(url: str) -> list[dict[str, Any]]:
    opener = build_opener(ProxyHandler({}), _NoRedirect)
    with opener.open(Request(url, method="GET"), timeout=2) as response:
        raw = response.read(1_048_577)
    if len(raw) > 1_048_576:
        raise ValueError("Ollama model list exceeds 1 MiB")
    body = json.loads(raw)
    if (
        not isinstance(body, dict)
        or not isinstance(body.get("models"), list)
        or not all(isinstance(x, dict) for x in body["models"])
    ):
        raise ValueError("Invalid Ollama model list")
    return body["models"]


def _identity(origin: str, item: dict[str, Any]) -> tuple[str, str | None, str | None, str] | None:
    name = item.get("model") or item.get("name")
    if not isinstance(name, str) or not name:
        return None
    digest = item.get("digest") if isinstance(item.get("digest"), str) else None
    details: dict[str, Any] = item["details"] if isinstance(item.get("details"), dict) else {}
    quant = (
        details.get("quantization_level")
        if isinstance(details.get("quantization_level"), str)
        else None
    )
    return name, digest, quant, f"{origin}|{name}|{digest or 'unknown'}|{quant or 'unknown'}"


def discover_ollama(endpoint: str = "http://127.0.0.1:11434") -> dict[str, Any]:
    try:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.port is None
        ):
            raise ValueError("Ollama discovery requires a loopback HTTP endpoint")
        origin = f"http://{parsed.netloc}"
    except (ValueError, TypeError) as error:
        return {"endpoint": endpoint, "models": [], "error": str(error)}
    try:
        installed = _entries(f"{origin}/api/tags")
    except (OSError, ValueError, HTTPError, URLError) as error:
        return {"endpoint": origin, "models": [], "error": str(error)}
    try:
        loaded = _entries(f"{origin}/api/ps")
        loaded_ids: set[str] | None = {
            identity[3] for item in loaded if (identity := _identity(origin, item))
        }
        error_message = None
    except (OSError, ValueError, HTTPError, URLError) as error:
        loaded_ids = None
        error_message = str(error)
    models = []
    for item in installed:
        identity = _identity(origin, item)
        if identity is None:
            continue
        name, digest, quant, model_id = identity
        models.append(
            {
                "id": model_id,
                "name": name,
                "digest": digest,
                "quantization": quant,
                "installed": True,
                "loaded": None if loaded_ids is None else model_id in loaded_ids,
            }
        )
    return {"endpoint": origin, "models": models, "error": error_message}
