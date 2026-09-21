from julius.economics import analyze_task


PRICE = {
    "id": "p", "modelId": "m", "providerId": "vendor", "source": "contract",
    "tier": "standard", "currency": "USD", "effectiveAt": "2026-01-01T00:00:00Z",
    "ratesPerMillion": {"inputUncached": 10, "cacheRead": 1, "cacheWrite": 20, "output": 30},
}


def usage(name: str, input_tokens: int | None, output_tokens: int | None = 100, *,
          cache_read: int | None = 0, complete: bool = True, category: str = "primary",
          model: str | None = "m", location: str = "remote") -> dict:
    return {
        "eventId": name, "eventType": "usage", "taskId": "task", "occurredAt": "2026-09-21T00:00:00Z",
        "modelId": model, "providerId": "vendor", "executionLocation": location,
        "evidence": "provider_reported", "payload": {"callId": name, "inputTokens": input_tokens,
        "outputTokens": output_tokens, "cacheReadTokens": cache_read, "cacheWriteTokens": 0,
        "priceSnapshotId": "p", "category": category, "complete": complete, "costUsd": None,
        "costProvenance": None},
    }


def baseline(*calls: dict) -> dict:
    return {"id": "base", "taskId": "task", "evidence": "controlled_experiment", "calls": list(calls)}


def base_call(name: str, count: int, output: int = 100, *, cache_read: int = 0) -> dict:
    return {"callId": name, "modelId": "m", "providerId": "vendor",
            "occurredAt": "2026-09-21T00:00:00Z", "inputTokens": count,
            "outputTokens": output, "cacheReadTokens": cache_read, "cacheWriteTokens": 0,
            "priceSnapshotId": "p"}


def transform(name: str, before: int, after: int, parent: str | None = None) -> dict:
    return {"eventId": name, "eventType": "transform", "taskId": "task", "modelId": "m",
            "evidence": "tokenizer_counted", "payload": {"transformId": name,
            "parentTransformId": parent, "inputArtifactId": "a" if parent else "original",
            "outputArtifactId": "b" if parent else "a", "inputTokens": before,
            "outputTokens": after, "scope": "request", "tokenizer": "tok", "sent": True}}


def test_chain_reduction_is_marginal() -> None:
    result = analyze_task([usage("c", 3000), transform("one", 10000, 4000),
                           transform("two", 4000, 3000, "one")], coverage_complete=True)
    assert result["directInputReductionTokens"] == 7000
    assert [t["marginalInputReductionTokens"] for t in result["transforms"]] == [6000, 1000]
    assert result["outputSavingsTokens"] is None
    assert result["observedOutputTokens"] == 100


def test_retries_and_auxiliary_are_charged_once() -> None:
    result = analyze_task([usage("a", 1000), usage("b", 1000), usage("aux", 500, category="auxiliary")],
                          baseline(base_call("base", 3000)), {"p": PRICE}, coverage_complete=True)
    assert result["currentModeledCostUsd"] == 0.034
    assert result["auxiliaryAndRetryCostIncludedUsd"] == 0.008
    assert result["netModeledSavingsUsd"] == 0.033 - 0.034


def test_unknown_model_and_interrupted_stream_unknown() -> None:
    assert analyze_task([usage("c", 100, model=None)], baseline(base_call("base", 100)),
                        {"p": PRICE}, coverage_complete=True)["netModeledSavingsUsd"] is None
    result = analyze_task([usage("c", None, None, cache_read=None, complete=False)],
                          baseline(base_call("base", 100)), {"p": PRICE}, coverage_complete=True)
    assert result["currentModeledCostUsd"] is None
    assert result["netModeledSavingsUsd"] is None
    assert result["coverageComplete"] is False


def test_warm_cache_can_make_compression_cost_more() -> None:
    result = analyze_task([usage("c", 3000)], baseline(base_call("base", 10000, cache_read=10000)),
                          {"p": PRICE}, coverage_complete=True)
    assert result["netModeledSavingsUsd"] < 0


def test_different_tokenizers_not_subtracted() -> None:
    first = transform("one", 10000, 4000)
    second = transform("two", 4000, 3000, "one")
    second["payload"]["tokenizer"] = "other"
    result = analyze_task([usage("c", 3000), first, second], coverage_complete=True)
    assert result["directInputReductionTokens"] is None
    assert result["transforms"][1]["marginalInputReductionTokens"] is None


def test_unknown_call_id_keeps_task_incomplete_and_cost_unknown() -> None:
    interrupted = usage("stream", None, None, cache_read=None, complete=False)
    interrupted["payload"]["callId"] = None
    result = analyze_task([usage("known", 100), interrupted],
                          baseline(base_call("base", 100)), {"p": PRICE}, coverage_complete=True)
    assert result["usageRecordsWithoutCallId"] == 1
    assert result["coverageComplete"] is False
    assert result["calls"][1]["callId"] is None
    assert result["calls"][1]["modeledCostUsd"] is None
    assert result["currentModeledCostUsd"] is None
    assert result["netModeledSavingsUsd"] is None
    assert result["observedInputTokens"] is None


def test_multiple_unknown_call_ids_are_distinct_incomplete_records() -> None:
    first = usage("first", None, None, complete=False)
    second = usage("second", None, None, complete=False)
    first["payload"]["callId"] = None
    second["payload"]["callId"] = None
    result = analyze_task([first, second], coverage_complete=True)
    assert result["usageRecordsWithoutCallId"] == 2
    assert len(result["calls"]) == 2
    assert result["currentModeledCostUsd"] is None


def test_orphan_parent_cannot_be_treated_as_root() -> None:
    orphan = transform("second", 4000, 3000, "missing")
    result = analyze_task([usage("c", 3000), orphan], coverage_complete=True)
    assert result["transforms"][0]["marginalInputReductionTokens"] is None
    assert result["directInputReductionTokens"] is None


def test_output_difference_needs_comparable_complete_task() -> None:
    reference = baseline(base_call("base", 1000, output=200))
    assert analyze_task([usage("current", 900, 150)], reference,
                        coverage_complete=True)["outputSavingsTokens"] is None
    reference["outputComparable"] = True
    result = analyze_task([usage("current", 900, 150)], reference,
                          coverage_complete=True)
    assert result["outputSavingsTokens"] == 50
    assert result["outputSavingsEvidence"] == "controlled_experiment"
    assert result["outputSavingsScope"] == "task_comparison"
    assert analyze_task([usage("current", 900, 250)], reference,
                        coverage_complete=True)["outputSavingsTokens"] == -50
    assert analyze_task([usage("current", 900, None, complete=False)], reference,
                        coverage_complete=True)["outputSavingsTokens"] is None
    assert analyze_task([usage("current", 900, 150)], reference,
                        coverage_complete=False)["outputSavingsTokens"] is None
