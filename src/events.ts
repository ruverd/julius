export type Evidence = "provider_reported" | "runtime_reported" | "tokenizer_counted" | "heuristic_estimate" | "reconstructed_baseline" | "controlled_experiment";
export type ExecutionLocation = "local" | "remote" | "unknown";
export type TransformScope = "tool_output" | "request" | "attempt" | "task" | "experiment";
export type UsageCategory = "primary" | "auxiliary" | "restoration";

export interface EventBase {
  schemaVersion: 1;
  eventId: string;
  occurredAt: string;
  sourceId: string;
  sourceEventId: string;
  projectId: string;
  taskId: string | null;
  sessionId: string;
  requestId: string | null;
  attemptId: string | null;
  clientId: string;
  adapterVersion: string;
  modelId: string | null;
  providerId: string | null;
  executionLocation: ExecutionLocation;
  evidence: Evidence;
}
export type EconomyEvent = EventBase & (
  | { eventType: "transform"; payload: { scope: TransformScope; inputTokens: number | null; outputTokens: number | null; tokenizer: string | null; transformId: string; parentTransformId: string | null; inputArtifactId: string | null; outputArtifactId: string | null; strategy: string; sent: boolean } }
  | { eventType: "usage"; payload: { inputTokens: number | null; outputTokens: number | null; cacheReadTokens: number | null; cacheWriteTokens: number | null; complete: boolean; category: UsageCategory; callId: string | null; costUsd: number | null; observationScope?: 'call' | 'session_delta'; rawUsage?: Record<string, unknown>; normalizerVersion?: string; costProvenance?: { priceSource: string; priceDate: string; priceModelId: string } | null } }
  | { eventType: "decision"; payload: { decision: string; reason: string | null; strategy: string | null } }
  | { eventType: "outcome"; payload: { outcome: string; reason: string | null } }
  | { eventType: "reconciliation"; payload: { targetEventId: string; effectiveInputTokens: number | null; effectiveOutputTokens: number | null; effectiveCacheReadTokens: number | null; effectiveCacheWriteTokens: number | null; effectiveCostUsd: number | null; effectiveCostProvenance?: { priceSource: string; priceDate: string; priceModelId: string } | null; effectiveComplete?: boolean; reason: string } }
);

const nonempty = (v: unknown): v is string => typeof v === "string" && v.trim().length > 0;
const nullableString = (v: unknown): v is string | null => v === null || nonempty(v);
const count = (v: unknown): v is number | null => v === null || (typeof v === "number" && Number.isSafeInteger(v) && v >= 0);
const money = (v: unknown): v is number | null => v === null || (typeof v === "number" && Number.isFinite(v) && v >= 0);
const validCostProvenance = (v: unknown): boolean => record(v) && nonempty(v.priceSource) && /^\d{4}-\d{2}-\d{2}$/.test(String(v.priceDate)) && nonempty(v.priceModelId);
const record = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const utc = (v: unknown): v is string => typeof v === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(v) && !Number.isNaN(Date.parse(v)) && new Date(v).toISOString() === v;
export function normalizeUtc(value: string): string { const date = new Date(value); if (!Number.isFinite(date.getTime())) throw new Error("Invalid UTC date"); return date.toISOString(); }

export function validateEvent(input: unknown): EconomyEvent {
  if (!record(input)) throw new Error("Event must be an object");
  if (Buffer.byteLength(JSON.stringify(input)) > 65536) throw new Error('Event exceeds 64 KiB limit');
  const e = input;
  if (e.schemaVersion !== 1 || !nonempty(e.eventId) || !utc(e.occurredAt) || !nonempty(e.sourceId) || !nonempty(e.sourceEventId) || !nonempty(e.projectId)) throw new Error("Invalid event envelope");
  for (const key of ["sessionId", "clientId", "adapterVersion"]) if (!nonempty(e[key])) throw new Error(`Invalid ${key}`);
  for (const key of ["taskId", "requestId", "attemptId", "modelId", "providerId"]) if (!nullableString(e[key])) throw new Error(`Invalid ${key}`);
  if (!["local", "remote", "unknown"].includes(String(e.executionLocation))) throw new Error("Invalid execution location");
  if (!["provider_reported", "runtime_reported", "tokenizer_counted", "heuristic_estimate", "reconstructed_baseline", "controlled_experiment"].includes(String(e.evidence))) throw new Error("Invalid evidence");
  if (!record(e.payload)) throw new Error("Invalid payload");
  const p = e.payload;
  switch (e.eventType) {
    case "transform":
      if (!["tool_output", "request", "attempt", "task", "experiment"].includes(String(p.scope)) || !count(p.inputTokens) || !count(p.outputTokens) || !nullableString(p.tokenizer) || !nonempty(p.transformId) || !nullableString(p.parentTransformId) || !nullableString(p.inputArtifactId) || !nullableString(p.outputArtifactId) || !nonempty(p.strategy) || typeof p.sent !== "boolean") throw new Error("Invalid transform payload");
      break;
    case "usage":
      if (![p.inputTokens, p.outputTokens, p.cacheReadTokens, p.cacheWriteTokens].every(count) || typeof p.complete !== "boolean" || !["primary", "auxiliary", "restoration"].includes(String(p.category)) || !nullableString(p.callId) || !money(p.costUsd) || (p.costUsd !== null && (!nonempty(e.modelId) || !validCostProvenance(p.costProvenance)))) throw new Error("Invalid usage payload");
      if (p.observationScope !== undefined && p.observationScope !== 'call' && p.observationScope !== 'session_delta') throw new Error('Invalid observation scope');
      if (p.rawUsage !== undefined && !record(p.rawUsage)) throw new Error('Invalid original usage counters');
      if (p.normalizerVersion !== undefined && !nonempty(p.normalizerVersion)) throw new Error('Invalid normalizer version');
      if (p.inputTokens !== null && p.cacheReadTokens !== null && Number(p.cacheReadTokens) > Number(p.inputTokens)) throw new Error('Cache reads exceed normalized input');
      break;
    case "decision":
      if (!nonempty(p.decision) || !nullableString(p.reason) || !nullableString(p.strategy)) throw new Error("Invalid decision payload");
      break;
    case "outcome":
      if (!nonempty(p.outcome) || !nullableString(p.reason)) throw new Error("Invalid outcome payload");
      break;
    case "reconciliation":
      if (!nonempty(p.targetEventId) || ![p.effectiveInputTokens, p.effectiveOutputTokens, p.effectiveCacheReadTokens, p.effectiveCacheWriteTokens].every(count) || !money(p.effectiveCostUsd) || (p.effectiveCostUsd !== null && (!nonempty(e.modelId) || !validCostProvenance(p.effectiveCostProvenance))) || (p.effectiveComplete !== undefined && typeof p.effectiveComplete !== "boolean") || !nonempty(p.reason)) throw new Error("Invalid reconciliation payload");
      break;
    default: throw new Error("Unknown event type");
  }
  return input as unknown as EconomyEvent;
}
