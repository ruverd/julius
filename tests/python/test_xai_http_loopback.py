"""Real local HTTP transport checks; never contacts xAI or uses a real credential."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

from julius import xai


@contextmanager
def local_responses(*, status=200, body=b"{}", location=None):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            calls.append({
                "path": self.path,
                "body": self.rfile.read(length),
                "authorization": self.headers.get("Authorization"),
                "content_type": self.headers.get("Content-Type"),
            })
            self.send_response(status)
            if location is not None:
                self.send_header("Location", location)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1/responses", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_default_transport_posts_exact_request_once_and_parses_usage(monkeypatch):
    response = json.dumps({
        "id": "resp_local", "model": "grok-fixture-actual", "status": "completed",
        "output": [], "usage": {
            "input_tokens": 120, "output_tokens": 40, "total_tokens": 160,
            "input_tokens_details": {"cached_tokens": 30},
            "output_tokens_details": {"reasoning_tokens": 5},
            "cost_in_usd_ticks": 150_000,
        },
    }).encode()
    request = {
        "model": "grok-fixture-alias", "input": [
            {"role": "system", "content": "Fixture instruction"},
            {"role": "user", "content": "Fixture question"},
        ],
        "tools": [{"type": "function", "name": "lookup", "parameters": {"type": "object"}}],
    }
    with local_responses(body=response) as (endpoint, calls):
        monkeypatch.setattr(xai, "ENDPOINT", endpoint)
        result = xai.XAIAdapter().send_once(request, "synthetic-test-key")
    assert len(calls) == 1
    assert calls[0]["path"] == "/v1/responses"
    assert calls[0]["body"] == xai.XAIAdapter().prepare(request)
    assert calls[0]["authorization"] == "Bearer synthetic-test-key"
    assert calls[0]["content_type"] == "application/json"
    assert result.complete is True
    assert result.requested_model == "grok-fixture-alias"
    assert result.actual_model == "grok-fixture-actual"
    assert (result.input_tokens, result.output_tokens, result.cached_input_tokens) == (120, 40, 30)
    assert result.reasoning_tokens == 5 and result.cost_ticks == 150_000


def test_http_error_redirect_and_oversize_are_incomplete_without_retry(monkeypatch):
    request = {"model": "grok-fixture", "input": "Synthetic"}
    for status, body, location, expected in (
        (503, b"error", None, "HTTP 503"),
        (302, b"redirect", "https://example.invalid/secret", "HTTP 302"),
        (200, b"x" * 65, None, "Invalid or oversized provider response"),
    ):
        with local_responses(status=status, body=body, location=location) as (endpoint, calls):
            monkeypatch.setattr(xai, "ENDPOINT", endpoint)
            if status == 200:
                monkeypatch.setattr(xai, "MAX_RESPONSE_BYTES", 64)
            result = xai.XAIAdapter().send_once(request, "synthetic-test-key")
        assert len(calls) == 1
        assert result.complete is False and result.error == expected
        assert result.input_tokens is None and result.output_tokens is None
