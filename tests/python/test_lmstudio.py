"""Fixture-only tests for read-only LM Studio discovery."""

import json
from urllib.error import URLError

from julius import lmstudio


class Response:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, limit):
        return self.data[:limit]


def test_lists_installed_and_loaded_with_quantization(monkeypatch):
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append((request.full_url, request.get_method(), timeout))
            return Response(json.dumps({"models": [
                {"key": "publisher/loaded", "type": "llm", "display_name": "Loaded",
                 "quantization": {"name": "Q4_K_M", "bits_per_weight": 4},
                 "selected_variant": "publisher/loaded@q4_k_m",
                 "loaded_instances": [{"id": "instance-1", "config": {"context_length": 4096}}]},
                {"key": "publisher/installed", "type": "embedding", "loaded_instances": []},
            ]}).encode())

    monkeypatch.setattr(lmstudio, "build_opener", lambda *handlers: Opener())
    result = lmstudio.discover_lmstudio()
    assert calls == [("http://127.0.0.1:1234/api/v1/models", "GET", 2)]
    assert result["error"] is None
    assert result["models"][0]["installed"] is True
    assert result["models"][0]["loaded"] is True
    assert result["models"][0]["quantization"] == "Q4_K_M"
    assert result["models"][0]["digest"] is None
    assert "publisher/loaded@q4_k_m" in result["models"][0]["id"]
    assert result["models"][1]["loaded"] is False


def test_unknown_loaded_state_when_field_missing(monkeypatch):
    class Opener:
        def open(self, request, timeout):
            return Response(b'{"models":[{"key":"m"}]}')

    monkeypatch.setattr(lmstudio, "build_opener", lambda *handlers: Opener())
    assert lmstudio.discover_lmstudio()["models"][0]["loaded"] is None


def test_invalid_origins_do_not_open_network(monkeypatch):
    monkeypatch.setattr(lmstudio, "build_opener", lambda *handlers: (_ for _ in ()).throw(AssertionError()))
    for endpoint in (
        "https://127.0.0.1:1234", "http://example.com:1234", "http://127.0.0.1:1234/extra",
        "http://127.0.0.1:1234/?q=1", "http://user@127.0.0.1:1234", "http://localhost:1234",
    ):
        assert lmstudio.discover_lmstudio(endpoint)["models"] == []


def test_redirect_is_rejected():
    handler = lmstudio._NoRedirect()
    try:
        handler.redirect_request(None, None, 302, "Found", {}, "http://example.com")
    except URLError as error:
        assert "blocked" in str(error)
    else:
        raise AssertionError("Redirect accepted")


def test_malformed_and_oversized_results_fail_closed(monkeypatch):
    class Opener:
        data = b""

        def open(self, request, timeout):
            return Response(self.data)

    opener = Opener()
    monkeypatch.setattr(lmstudio, "build_opener", lambda *handlers: opener)
    for data in (b"{}", b'{"models":[1]}', b"x" * (lmstudio.MAX_RESPONSE_BYTES + 1)):
        opener.data = data
        result = lmstudio.discover_lmstudio()
        assert result["models"] == []
        assert result["error"] is not None
