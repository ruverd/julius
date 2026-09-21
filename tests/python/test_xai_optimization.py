"""The xAI candidate path must preserve the Responses protocol."""

import copy

import pytest

from julius.artifacts import ArtifactStore
from julius.xai_optimization import prepare_optimized_request


LINE = "ordinary repeated status line with enough detail for deterministic reduction and retrieval"
TEXT = "\n".join([LINE] * 8)
POLICY = {"mode": "safe", "version": "1.0.0", "approved": True}
TOOL = {"type": "function", "name": "julius_restore_artifact", "description": "Restore",
        "parameters": {"type": "object", "properties": {"artifact_id": {"type": "string"}},
                       "required": ["artifact_id"]}}


def request():
    return {"model": "grok-4.6", "previous_response_id": "resp_1", "store": False,
            "tools": [TOOL, {"type": "web_search"}],
            "input": [{"role": "system", "content": "Keep exact instructions"},
                      {"type": "function_call_output", "call_id": "call_1", "output": TEXT},
                      {"role": "user", "content": "Summarize"}]}


def test_candidate_preserves_request_and_recovers_original(tmp_path):
    store = ArtifactStore(tmp_path)
    source = request()
    untouched = copy.deepcopy(source)
    prepared = prepare_optimized_request(source, project_id="project", policy=POLICY,
                                         artifacts=store, recovery_handler_available=True)
    assert source == untouched
    assert prepared.candidate_only is True
    assert prepared.request["tools"] == source["tools"]
    assert prepared.request["previous_response_id"] == "resp_1"
    assert prepared.request["input"][0] == source["input"][0]
    assert prepared.request["input"][2] == source["input"][2]
    assert prepared.request["input"][1]["call_id"] == "call_1"
    receipt = prepared.receipts[0]
    assert receipt["realizedSavings"] is None
    if receipt["applied"]:
        artifact_id = receipt["lineage"]["originalArtifactId"]
        assert store.get("project", artifact_id) == TEXT
        assert prepared.request["input"][1]["output"] != TEXT
    else:
        assert prepared.request["input"][1]["output"] == TEXT


@pytest.mark.parametrize("change", [
    {"input": "plain text"},
    {"input": [{"role": "tool", "content": TEXT}]},
    {"input": [{"type": "function_call_output", "output": TEXT}]},
    {"tools": []},
])
def test_unsupported_or_unrecoverable_request_fails_closed(tmp_path, change):
    source = request()
    source.update(change)
    before = copy.deepcopy(source)
    with pytest.raises(ValueError):
        prepare_optimized_request(source, project_id="project", policy=POLICY,
                                  artifacts=ArtifactStore(tmp_path),
                                  recovery_handler_available=True)
    assert source == before


def test_handler_attestation_required(tmp_path):
    with pytest.raises(ValueError, match="recovery"):
        prepare_optimized_request(request(), project_id="project", policy=POLICY,
                                  artifacts=ArtifactStore(tmp_path))


def test_failed_later_output_does_not_retain_partial_candidates(tmp_path):
    source = request()
    source["input"].append({
        "type": "function_call_output", "call_id": "call_2", "output": "x" * (1024 * 1024 + 1),
    })
    with pytest.raises(ValueError, match="too large"):
        prepare_optimized_request(source, project_id="project", policy=POLICY,
                                  artifacts=ArtifactStore(tmp_path),
                                  recovery_handler_available=True)
    assert list(tmp_path.rglob("*.txt")) == []


def test_known_julius_candidate_is_not_compressed_again_without_lineage(tmp_path):
    source = request()
    marker = "[repeated exact line 2/3; restore artifact 12345678-1234-1234-1234-123456789abc]"
    source["input"][1]["output"] = marker + "\n" + TEXT
    prepared = prepare_optimized_request(
        source, project_id="project", policy={**POLICY, "allowRecompression": True},
        artifacts=ArtifactStore(tmp_path), recovery_handler_available=True,
    )
    assert prepared.request == source
    assert prepared.receipts[0]["applied"] is False
    assert prepared.receipts[0]["reason"] == "recompression_requires_opt_in"
    assert list(tmp_path.rglob("*.txt")) == []
