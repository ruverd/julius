import json

from julius.importers import import_claude_transcript, import_codex_rollout


OPTIONS = {"projectId": "p", "sourceId": "file"}


def lines(*items):
    return "\n".join(json.dumps(item) for item in items)


def test_claude_deduplicates_and_reimport_is_stable():
    first = {
        "type": "assistant",
        "sessionId": "s",
        "timestamp": "2026-09-21T10:00:00Z",
        "message": {"id": "m", "usage": {"input_tokens": 10, "output_tokens": 1}},
    }
    second = {
        **first,
        "timestamp": "2026-09-21T10:00:01Z",
        "message": {
            "id": "m",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 4,
                "cache_read_input_tokens": 2,
                "cache_creation_input_tokens": 3,
            },
            "stop_reason": None,
        },
    }
    text = lines(first, second)
    result = import_claude_transcript(text, OPTIONS)
    assert len(result) == 1
    assert result[0]["payload"]["inputTokens"] == 15
    assert result[0]["payload"]["complete"] is False
    assert result[0]["eventId"] == import_claude_transcript(text, OPTIONS)[0]["eventId"]


def test_codex_cumulative_deltas_and_partial_baseline():
    def event(n, i, o):
        return {
            "type": "event_msg",
            "timestamp": f"2026-09-21T10:0{n}:00Z",
            "payload": {
                "type": "token_count",
                "info": {"total_token_usage": {"input_tokens": i, "output_tokens": o}},
            },
        }

    result = import_codex_rollout(lines(event(1, 100, 10), event(2, 120, 12)), OPTIONS)
    assert len(result) == 1
    assert result[0]["payload"]["inputTokens"] == 20
    assert result[0]["payload"]["cacheReadTokens"] is None
    assert result[0]["payload"]["observationScope"] == "session_delta"
    assert result[0]["modelId"] is None and result[0]["requestId"] is None


def test_codex_reset_and_duplicate_snapshot_are_not_added():
    def event(n, i):
        return {
            "type": "event_msg",
            "timestamp": f"2026-09-21T10:0{n}:00Z",
            "payload": {
                "type": "token_count",
                "info": {"total_token_usage": {"input_tokens": i, "output_tokens": i // 10}},
            },
        }

    meta = {"type": "session_meta", "payload": {"id": "s"}}
    result = import_codex_rollout(
        lines(meta, event(1, 100), event(2, 100), event(3, 2), event(4, 12)), OPTIONS
    )
    assert [item["payload"]["inputTokens"] for item in result] == [100, 10]
