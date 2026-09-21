# xAI transport loopback acceptance

`tests/python/test_xai_http_loopback.py` runs the actual urllib transport against a temporary `127.0.0.1` HTTP server. Tests send only synthetic requests and a synthetic key. They verify one POST with the serialized body and Authorization header, actual-model attribution, input/output/cache/reasoning counters, provider cost ticks, and incomplete results for HTTP errors, redirects, and oversized responses. No external network request or real xAI credential is used.

This establishes behavior of Julius's local HTTP path. It does **not** certify xAI's current Responses contract, account billing, function-call restoration, task quality, or input savings. Live xAI status remains experimental until a separately authorized real-account test records those facts.
