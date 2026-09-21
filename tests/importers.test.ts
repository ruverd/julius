import { expect, test } from "bun:test";
import { importClaudeTranscript, importCodexRollout } from "../src/importers";
import { validateEvent } from "../src/events";
import { Ledger } from "../src/ledger";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const options = { projectId: "project", sourceId: "selected-file" };
const jsonl = (...rows: object[]) => rows.map(row => JSON.stringify(row)).join("\n");

test("Claude duplicate streaming rows produce one latest incomplete usage record", () => {
  const common = { type: "assistant", sessionId: "s1", requestId: "req1" };
  const text = jsonl(
    { ...common, timestamp: "2026-09-21T10:00:00Z", message: { id: "msg1", model: "claude-x", usage: { input_tokens: 10, output_tokens: 1 } } },
    { ...common, timestamp: "2026-09-21T10:00:01Z", message: { id: "msg1", model: "claude-x", usage: { input_tokens: 10, output_tokens: 4, cache_read_input_tokens: 2, cache_creation_input_tokens: 3 }, stop_reason: null } },
  );
  const events = importClaudeTranscript(text, options);
  expect(events).toHaveLength(1);
  const event = validateEvent(events[0]);
  expect(event.sourceEventId).toBe("s1:message:msg1");
  if (event.eventType === "usage") expect(event.payload).toMatchObject({ inputTokens: 15, outputTokens: 4, cacheReadTokens: 2, cacheWriteTokens: 3, complete: false, costUsd: null });
});

test("Codex cumulative counters emit only positive increments and skip reset snapshots", () => {
  const meta = { timestamp: "2026-09-21T10:00:00Z", type: "session_meta", payload: { id: "s2" } };
  const counter = (minute: number, input: number, output: number, read?: number) => ({ timestamp: `2026-09-21T10:0${minute}:00Z`, type: "event_msg", payload: { type: "token_count", info: { total_token_usage: { input_tokens: input, output_tokens: output, ...(read === undefined ? {} : { cached_input_tokens: read }) } } } });
  const events = importCodexRollout(jsonl(meta, counter(1, 100, 10, 20), counter(2, 100, 10, 20), counter(3, 130, 15, 25), counter(4, 2, 1, 0), counter(5, 12, 3, 1)), options);
  expect(events).toHaveLength(3);
  expect(events.map(event => event.eventType === "usage" ? [event.payload.inputTokens, event.payload.outputTokens] : null)).toEqual([[100, 10], [30, 5], [10, 2]]);
  expect(events[0]?.eventType === "usage" && events[0].payload.cacheWriteTokens).toBeNull();
  expect(events.every(event => event.modelId === null && event.requestId === null && event.eventType === "usage" && event.payload.complete === false && event.payload.callId === null)).toBe(true);
  events.forEach(validateEvent);
});

test("Codex without session metadata uses first cumulative snapshot as baseline", () => {
  const counter = (input: number) => ({ timestamp: "2026-09-21T10:00:00Z", type: "event_msg", payload: { type: "token_count", info: { total_token_usage: { input_tokens: input, output_tokens: 1 } } } });
  const events = importCodexRollout(jsonl(counter(100), counter(120)), options);
  expect(events).toHaveLength(1);
  if (events[0]?.eventType === "usage") expect(events[0].payload.inputTokens).toBe(20);
});

test("reimporting the same selected transcript is idempotent in the ledger", () => {
  const text = jsonl({ type: "assistant", sessionId: "s1", timestamp: "2026-09-21T10:00:00Z", message: {
    id: "msg1", usage: { input_tokens: 10, output_tokens: 4, cache_read_input_tokens: 2, cache_creation_input_tokens: 3 }, stop_reason: "end_turn" } });
  const folder = mkdtempSync(join(tmpdir(), "julius-import-"));
  try {
    const ledger = new Ledger(join(folder, "ledger.db"));
    for (const event of importClaudeTranscript(text, options)) ledger.record(event);
    for (const event of importClaudeTranscript(text, options)) ledger.record(event);
    expect(ledger.events()).toHaveLength(1);
    ledger.close();
  } finally { rmSync(folder, { recursive: true, force: true }); }
});

test("invalid JSONL is explicit", () => {
  expect(() => importClaudeTranscript("{", options)).toThrow("Invalid JSONL line 1");
});

test('concatenated Codex sessions start separate counter baselines', () => {
  const meta = (id: string) => ({ type: 'session_meta', payload: { id } });
  const count = (input: number) => ({ timestamp: '2026-09-21T10:00:00Z', type: 'event_msg', payload: { type: 'token_count', info: { total_token_usage: { input_tokens: input, output_tokens: 10 } } } });
  const events = importCodexRollout(jsonl(meta('one'), count(100), meta('two'), count(130)), options);
  expect(events.map(event => event.eventType === 'usage' ? event.payload.inputTokens : null)).toEqual([100, 130]);
});
