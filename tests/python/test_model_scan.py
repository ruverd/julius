from julius.model_registry import ModelRegistry
from julius.model_scan import scan_models


def test_ollama_scan_stores_only_observed_facts(tmp_path, monkeypatch):
    calls = []

    def discover(endpoint):
        calls.append(endpoint)
        return {"endpoint": endpoint, "error": "loaded state unavailable", "models": [
            {"name": "alias:latest", "digest": "sha256:abc", "quantization": "Q4_K_M",
             "installed": True, "loaded": None},
        ]}

    monkeypatch.setattr("julius.model_scan.discover_ollama", discover)
    with ModelRegistry(tmp_path / "models.sqlite") as registry:
        result = scan_models(registry, provider="ollama", endpoint="http://127.0.0.1:11434")
        record = result["snapshots"][0]
        assert calls == ["http://127.0.0.1:11434"]
        assert result["error"] == "loaded state unavailable"
        assert record["state"] == "installed"
        assert record["responded_model"] is None
        assert record["alias"] is None
        assert record["context_window"] is None
        assert record["tool_capabilities"] == {}
        assert record["digest"] == "sha256:abc"
        assert registry.history(endpoint=record["endpoint"], requested_model="alias:latest") == [record]


def test_lmstudio_scan_is_endpoint_specific_and_append_only(tmp_path, monkeypatch):
    def discover(endpoint, *, api_token=None):
        assert api_token is None
        return {"endpoint": endpoint, "error": None, "models": [
            {"name": "model-a", "installed": True, "loaded": True, "digest": None,
             "quantization": None},
        ]}

    monkeypatch.setattr("julius.model_scan.discover_lmstudio", discover)
    with ModelRegistry(tmp_path / "models.sqlite") as registry:
        first = scan_models(registry, provider="lmstudio", endpoint="http://127.0.0.1:1234")
        second = scan_models(registry, provider="lmstudio", endpoint="http://127.0.0.1:1235")
        one = first["snapshots"][0]
        two = second["snapshots"][0]
        assert one["state"] == "loaded"
        assert one["identityId"] != two["identityId"]
        assert len(registry.history(endpoint=one["endpoint"], requested_model="model-a")) == 1
        assert len(registry.history(endpoint=two["endpoint"], requested_model="model-a")) == 1


def test_unavailable_discovery_does_not_invent_model(tmp_path, monkeypatch):
    monkeypatch.setattr("julius.model_scan.discover_ollama", lambda endpoint: {
        "endpoint": endpoint, "error": "Connection refused", "models": [],
    })
    with ModelRegistry(tmp_path / "models.sqlite") as registry:
        result = scan_models(registry, provider="ollama", endpoint="http://127.0.0.1:11434")
        assert result["snapshots"] == []
        assert result["error"] == "Connection refused"
        assert registry.latest(endpoint=result["endpoint"], requested_model="unknown") is None
