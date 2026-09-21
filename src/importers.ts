import { normalizeAnthropicUsage } from "./adapters";
import { validateEvent, type EconomyEvent } from "./events";
import { createHash } from "node:crypto";

export interface ImportOptions { projectId: string; sourceId: string }
type Row = Record<string, unknown>;
type UsageEvent = Extract<EconomyEvent, { eventType: "usage" }>;
const record = (value: unknown): Row | null => value !== null && typeof value === "object" && !Array.isArray(value) ? value as Row : null;
const string = (value: unknown): string | null => typeof value === "string" && value.trim() ? value : null;
const count = (value: unknown): number | null => typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null;
const stamp = (value: unknown): string | null => {
  if (typeof value !== "string") return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
};
function rows(text: string): Row[] {
  return text.split(/\r?\n/).flatMap((line, index) => {
    if (!line.trim()) return [];
    try { const parsed = record(JSON.parse(line)); if (!parsed) throw new Error("not an object"); return [parsed]; }
    catch (error) { throw new Error(`Invalid JSONL line ${index + 1}: ${error instanceof Error ? error.message : "parse failed"}`); }
  });
}
function base(options: ImportOptions, sessionId: string, sourceEventId: string, timestamp: string, clientId: string, requestId: string | null, modelId: string | null): Omit<UsageEvent, "eventType" | "payload"> {
  if (!options.projectId.trim() || !options.sourceId.trim()) throw new Error("projectId and sourceId are required");
  const eventId = createHash("sha256").update(JSON.stringify([options.projectId, options.sourceId, sourceEventId])).digest("hex");
  return { schemaVersion: 1, eventId, occurredAt: timestamp,
    sourceId: options.sourceId, sourceEventId, projectId: options.projectId, taskId: null,
    sessionId, requestId, attemptId: null, clientId, adapterVersion: "experimental-jsonl-1",
    modelId, providerId: clientId === "claude" ? "anthropic" : "openai",
    executionLocation: "unknown", evidence: "provider_reported" };
}

/** Explicit, read-only import of Claude Code assistant transcript rows. */
export function importClaudeTranscript(text: string, options: ImportOptions): EconomyEvent[] {
  const selected = new Map<string, { row: Row; message: Row; usage: Row; session: string; id: string; time: string }>();
  for (const row of rows(text)) {
    if (row.type !== "assistant") continue;
    const message = record(row.message);
    const usage = record(message?.usage);
    const id = string(message?.id);
    const time = stamp(row.timestamp);
    if (!message || !usage || !id || !time) continue;
    const session = string(row.sessionId) ?? options.sourceId;
    const key = `${session}:${id}`;
    const prior = selected.get(key);
    if (!prior || time >= prior.time) selected.set(key, { row, message, usage, session, id, time });
  }
  return [...selected.values()].map(({ row, message, usage, session, id, time }) => {
    const normalized = normalizeAnthropicUsage(usage);
    return validateEvent({ ...base(options, session, `${session}:message:${id}`, time, "claude", string(row.requestId) ?? id, string(message.model)),
      eventType: "usage", payload: { inputTokens: normalized.inputTokens, outputTokens: normalized.outputTokens,
        cacheReadTokens: normalized.cacheReadTokens, cacheWriteTokens: normalized.cacheWriteTokens,
        complete: string(message.stop_reason) !== null, category: "primary", callId: `${session}:${id}`, costUsd: null,
        observationScope: "call", rawUsage: usage, normalizerVersion: "anthropic-1" } });
  });
}

type Counters = { input: number; output: number; read: number | null; write: number | null };
function codexCounters(value: unknown): Counters | null {
  const usage = record(value);
  const input = count(usage?.input_tokens), output = count(usage?.output_tokens);
  const read = count(usage?.cached_input_tokens), write = count(usage?.cache_write_input_tokens);
  return input !== null && output !== null ? { input, output, read, write } : null;
}
function delta(current: Counters, previous: Counters): Counters | null {
  if (current.input < previous.input || current.output < previous.output ||
    (current.read !== null && previous.read !== null && current.read < previous.read) ||
    (current.write !== null && previous.write !== null && current.write < previous.write)) return null;
  return { input: current.input - previous.input, output: current.output - previous.output,
    read: current.read === null || previous.read === null ? null : current.read - previous.read,
    write: current.write === null || previous.write === null ? null : current.write - previous.write };
}

/** Explicit, read-only import of Codex rollout cumulative token_count events. */
export function importCodexRollout(text: string, options: ImportOptions): EconomyEvent[] {
  let session = options.sourceId;
  let previous: Counters = { input: 0, output: 0, read: 0, write: 0 };
  let hasSessionStart = false;
  let hasBaseline = false;
  const result: EconomyEvent[] = [];
  for (const [index, row] of rows(text).entries()) {
    const payload = record(row.payload);
    if (row.type === "session_meta") {
      session = string(payload?.id) ?? session;
      previous = { input: 0, output: 0, read: 0, write: 0 };
      hasBaseline = false;
      hasSessionStart = true;
      continue;
    }
    if (row.type !== "event_msg" || payload?.type !== "token_count") continue;
    const info = record(payload.info);
    const current = codexCounters(info?.total_token_usage);
    const time = stamp(row.timestamp);
    if (!current || !time) continue;
    if (!hasBaseline) {
      hasBaseline = true;
      if (!hasSessionStart) { previous = current; continue; }
    }
    const change = delta(current, previous);
    if (!change) { previous = current; continue; }
    previous = current;
    if (Object.values(change).every(value => value === 0 || value === null)) continue;
    result.push(validateEvent({ ...base(options, session, `${session}:token_count:${index}`, time, "codex", null, null),
      eventType: "usage", payload: { inputTokens: change.input, outputTokens: change.output,
        cacheReadTokens: change.read, cacheWriteTokens: change.write,
        complete: false, category: "primary", callId: null, costUsd: null,
        observationScope: "session_delta", rawUsage: record(info?.total_token_usage) ?? {},
        normalizerVersion: "codex-cumulative-1" } }));
  }
  return result;
}
