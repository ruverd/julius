import pytest

from julius.artifacts import ArtifactStore
from julius.request_measurement import measure_request_pair
from julius.xai import XAIAdapter
from julius.xai_optimization import prepare_optimized_request


TOOL = {"type": "function", "name": "julius_restore_artifact",
        "parameters": {"type": "object", "properties": {"artifact_id": {"type": "string"}},
                       "required": ["artifact_id"]}}
LINE = "ordinary repeated status line with enough detail for deterministic reduction and retrieval"
POLICY = {"mode": "safe", "version": "1.0.0", "approved": True}


def request():
    return {"model": "grok-pinned", "tools": [TOOL],
            "instructions": "Preserve every instruction and tool schema",
            "input": [{"type": "function_call_output", "call_id": "call_1",
                       "output": "\n".join([LINE] * 8)}]}


def test_whole_request_bytes_include_all_fields_and_unknown_tokens(tmp_path):
    source = request()
    prepared = prepare_optimized_request(
        source, project_id="p", policy=POLICY, artifacts=ArtifactStore(tmp_path),
        recovery_handler_available=True,
    )
    measurement = prepared.measurement
    assert measurement is not None
    assert measurement["beforeBytes"] == len(XAIAdapter().prepare(source))
    assert measurement["afterBytes"] == len(XAIAdapter().prepare(prepared.request))
    assert measurement["deltaBytes"] == measurement["beforeBytes"] - measurement["afterBytes"]
    assert measurement["beforeTokens"] is None
    assert measurement["deltaTokens"] is None
    assert measurement["providerMeasured"] is False
    assert measurement["sent"] is False


def test_explicit_pinned_counter_keeps_signed_delta():
    source = {"model": "grok-pinned", "input": "a", "tools": [TOOL]}
    larger = {**source, "input": "a much larger text"}
    measured = measure_request_pair(source, larger, token_counter=lambda text: len(text),
                                    model_id="grok-pinned", tokenizer_id="fixture-v1")
    assert measured["deltaBytes"] < 0
    assert measured["deltaTokens"] < 0
    assert measured["tokenEvidence"] == "caller_counted"
    assert measured["tokenCountingBasis"] == "serialized_request"
    assert measured["modelId"] == "grok-pinned"
    assert measured["tokenizerId"] == "fixture-v1"


def test_invalid_counter_pin_or_output_fails_closed():
    source = {"model": "grok-pinned", "input": "a"}
    with pytest.raises(ValueError, match="matching model"):
        measure_request_pair(source, source, token_counter=lambda _: 1,
                             model_id="other-model", tokenizer_id="tok")
    with pytest.raises(ValueError, match="invalid count"):
        measure_request_pair(source, source, token_counter=lambda _: True,
                             model_id="grok-pinned", tokenizer_id="tok")
    with pytest.raises(ValueError, match="requires a token counter"):
        measure_request_pair(source, source, token_counting_basis="model_input")
    with pytest.raises(ValueError, match="Unknown token counting basis"):
        measure_request_pair(source, source, token_counting_basis="unknown")


def test_preparation_exposes_pinned_measurement(tmp_path):
    prepared = prepare_optimized_request(
        request(), project_id="p", policy=POLICY, artifacts=ArtifactStore(tmp_path),
        recovery_handler_available=True, token_counter=lambda text: len(text),
        tokenizer_model_id="grok-pinned", tokenizer_id="fixture-v1",
    )
    assert prepared.measurement is not None
    assert prepared.measurement["deltaTokens"] == prepared.measurement["deltaBytes"]
    assert prepared.measurement["tokenCountingBasis"] == "serialized_request"
