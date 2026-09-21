from julius.adapters import normalize_anthropic_usage, normalize_openai_usage
import io
from urllib.error import URLError
from urllib.request import ProxyHandler

import pytest

from julius.models import _NoRedirect, _entries, discover_ollama, doctor


def test_openai_counts_cache_and_reasoning_once():
    result = normalize_openai_usage(
        {
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
                "input_tokens_details": {"cached_tokens": 40},
                "output_tokens_details": {"reasoning_tokens": 7},
            }
        }
    )
    assert (result["inputTokens"], result["uncachedInputTokens"], result["reasoningTokens"]) == (
        100,
        60,
        7,
    )
    assert result["totalTokens"] == 120 and result["costUsd"] is None
    assert normalize_openai_usage({"input_tokens": True})["inputTokens"] is None


def test_anthropic_full_input_requires_all_cache_categories():
    result = normalize_anthropic_usage(
        {
            "usage": {
                "input_tokens": 10,
                "cache_read_input_tokens": 5,
                "cache_creation_input_tokens": 3,
                "output_tokens": 2,
            }
        }
    )
    assert (result["inputTokens"], result["uncachedInputTokens"], result["totalTokens"]) == (
        18,
        10,
        20,
    )
    assert (
        normalize_anthropic_usage({"input_tokens": 10, "output_tokens": 2})["inputTokens"] is None
    )
    assert (
        normalize_anthropic_usage(
            {
                "input_tokens": True,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "output_tokens": 2,
            }
        )["inputTokens"]
        is None
    )


def test_doctor_does_not_claim_live_capabilities(monkeypatch):
    class Completed:
        returncode = 0
        stdout = "client 1.0\n"
        stderr = ""

    monkeypatch.setattr("julius.models.subprocess.run", lambda *a, **kw: Completed())
    result = doctor()
    assert all(
        client["installed"] and client["capability"] == "unsupported"
        for client in result["clients"]
    )
    assert all(not any(client["capabilities"].values()) for client in result["clients"])


def test_ollama_keeps_installed_when_ps_fails(monkeypatch):
    def entries(url):
        if url.endswith("/api/ps"):
            raise ValueError("unavailable")
        return [{"model": "m:latest", "digest": "sha", "details": {"quantization_level": "Q4"}}]

    monkeypatch.setattr("julius.models._entries", entries)
    result = discover_ollama()
    assert result["models"][0]["loaded"] is None
    assert result["error"] == "unavailable"
    assert discover_ollama("https://example.com")["models"] == []


def test_ollama_discovery_disables_proxies_and_bounds_json(monkeypatch):
    seen = []

    class Opener:
        def open(self, request, timeout):
            assert timeout == 2
            return io.BytesIO(b'{"models": []}')

    def build(*handlers):
        seen.extend(handlers)
        return Opener()

    monkeypatch.setattr("julius.models.build_opener", build)
    assert _entries("http://127.0.0.1:11434/api/tags") == []
    assert any(isinstance(item, ProxyHandler) and item.proxies == {} for item in seen)
    assert any(item is _NoRedirect or isinstance(item, _NoRedirect) for item in seen)

    class LargeOpener:
        def open(self, request, timeout):
            return io.BytesIO(b" " * 1_048_577)

    monkeypatch.setattr("julius.models.build_opener", lambda *handlers: LargeOpener())
    with pytest.raises(ValueError, match="1 MiB"):
        _entries("http://127.0.0.1:11434/api/tags")


def test_redirect_is_rejected():
    with pytest.raises(URLError, match="redirect blocked"):
        _NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://example.com")
