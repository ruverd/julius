import type { Evidence } from "./events";

export interface PriceSnapshot {
  readonly id: string;
  readonly modelId: string;
  readonly providerId: string;
  readonly source: string;
  readonly effectiveAt: string;
  readonly currency: "USD";
  readonly tier: string;
  /** Caller supplied USD per million tokens. Null means unavailable. */
  readonly ratesPerMillion: Readonly<{
    inputUncached: number | null;
    cacheRead: number | null;
    cacheWrite: number | null;
    output: number | null;
  }>;
}

export interface PricedUsage {
  readonly callId: string;
  readonly modelId: string | null;
  readonly providerId: string | null;
  readonly inputTokens: number | null;
  readonly cacheReadTokens: number | null;
  readonly cacheWriteTokens: number | null;
  readonly outputTokens: number | null;
  readonly priceSnapshotId: string | null;
}

export interface ModeledCost {
  readonly callId: string;
  readonly modeledCostUsd: number | null;
  readonly priceSnapshotId: string | null;
}

export interface ExplicitOverhead {
  readonly id: string;
  readonly kind: "local" | "external";
  readonly costUsd: number | null;
}

export interface ComparableBaseline {
  readonly id: string;
  readonly evidence: Extract<Evidence, "reconstructed_baseline" | "controlled_experiment">;
  readonly modeledCostUsd: number | null;
  readonly comparisonScope: string;
}

const validCount = (value: unknown): boolean => value === null || typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const validMoney = (value: unknown): boolean => value === null || typeof value === "number" && Number.isFinite(value) && value >= 0;
const nonempty = (value: string): boolean => value.trim().length > 0;

function validateSnapshot(snapshot: PriceSnapshot): void {
  if (![snapshot.id, snapshot.modelId, snapshot.providerId, snapshot.source, snapshot.tier].every(nonempty) ||
    snapshot.currency !== "USD" || Number.isNaN(Date.parse(snapshot.effectiveAt))) throw new Error("Invalid price snapshot");
  if (!snapshot.ratesPerMillion || !["inputUncached", "cacheRead", "cacheWrite", "output"].every(key =>
    Object.hasOwn(snapshot.ratesPerMillion, key) && validMoney(snapshot.ratesPerMillion[key as keyof PriceSnapshot["ratesPerMillion"]]))) throw new Error("Invalid price rate");
}

/** Computes a modeled token cost, never a provider measurement. */
export function priceUsage(usage: PricedUsage, snapshot: PriceSnapshot | null): ModeledCost {
  if (!nonempty(usage.callId) || ![usage.inputTokens, usage.cacheReadTokens, usage.cacheWriteTokens, usage.outputTokens].every(validCount)) throw new Error("Invalid usage for pricing");
  if (!snapshot || !usage.priceSnapshotId || snapshot.id !== usage.priceSnapshotId ||
    usage.modelId !== snapshot.modelId || usage.providerId !== snapshot.providerId) {
    return { callId: usage.callId, modeledCostUsd: null, priceSnapshotId: usage.priceSnapshotId };
  }
  validateSnapshot(snapshot);
  const { inputTokens, cacheReadTokens, cacheWriteTokens, outputTokens } = usage;
  if (inputTokens === null || cacheReadTokens === null || cacheWriteTokens === null || outputTokens === null) {
    return { callId: usage.callId, modeledCostUsd: null, priceSnapshotId: snapshot.id };
  }
  const uncached = inputTokens - cacheReadTokens - cacheWriteTokens;
  if (uncached < 0) throw new Error("Cache counters exceed input total");
  const items: readonly [number, number | null][] = [
    [uncached, snapshot.ratesPerMillion.inputUncached],
    [cacheReadTokens, snapshot.ratesPerMillion.cacheRead],
    [cacheWriteTokens, snapshot.ratesPerMillion.cacheWrite],
    [outputTokens, snapshot.ratesPerMillion.output],
  ];
  if (items.some(([tokens, rate]) => tokens > 0 && rate === null)) return { callId: usage.callId, modeledCostUsd: null, priceSnapshotId: snapshot.id };
  const cost = items.reduce((sum, [tokens, rate]) => sum + tokens * (rate ?? 0) / 1_000_000, 0);
  if (!Number.isFinite(cost)) throw new Error("Modeled cost overflow");
  return { callId: usage.callId, modeledCostUsd: cost, priceSnapshotId: snapshot.id };
}

export interface Comparison {
  readonly baselineId: string;
  readonly baselineEvidence: ComparableBaseline["evidence"];
  readonly baselineModeledCostUsd: number | null;
  readonly observedModeledCostUsd: number | null;
  readonly overheadUsd: number | null;
  readonly netModeledSavingsUsd: number | null;
}

/** Signed modeled comparison. Usage and overhead IDs must be unique within the supplied scope. */
export function compareModeledCosts(baseline: ComparableBaseline, usage: readonly ModeledCost[], overhead: readonly ExplicitOverhead[] = [], coverageComplete = false): Comparison {
  if (!nonempty(baseline.id) || !nonempty(baseline.comparisonScope) ||
    !["reconstructed_baseline", "controlled_experiment"].includes(baseline.evidence) ||
    !validMoney(baseline.modeledCostUsd)) throw new Error("Invalid comparable baseline");
  const callIds = new Set<string>(), overheadIds = new Set<string>();
  for (const item of usage) {
    if (!nonempty(item.callId) || callIds.has(item.callId) || !validMoney(item.modeledCostUsd)) throw new Error("Invalid or duplicate call ID");
    callIds.add(item.callId);
  }
  for (const item of overhead) {
    if (!nonempty(item.id) || overheadIds.has(item.id) || !["local", "external"].includes(item.kind) || !validMoney(item.costUsd)) throw new Error("Invalid or duplicate overhead ID");
    overheadIds.add(item.id);
  }
  const observed = (usage.length > 0 || coverageComplete) && usage.every(item => item.modeledCostUsd !== null)
    ? usage.reduce((sum, item) => sum + (item.modeledCostUsd ?? 0), 0) : null;
  const overheadCost = overhead.every(item => item.costUsd !== null)
    ? overhead.reduce((sum, item) => sum + (item.costUsd ?? 0), 0) : null;
  if ((observed !== null && !Number.isFinite(observed)) || (overheadCost !== null && !Number.isFinite(overheadCost))) throw new Error("Modeled cost overflow");
  const net = baseline.modeledCostUsd !== null && observed !== null && overheadCost !== null
    ? baseline.modeledCostUsd - observed - overheadCost : null;
  if (net !== null && !Number.isFinite(net)) throw new Error("Modeled cost overflow");
  return { baselineId: baseline.id, baselineEvidence: baseline.evidence,
    baselineModeledCostUsd: baseline.modeledCostUsd, observedModeledCostUsd: observed,
    overheadUsd: overheadCost, netModeledSavingsUsd: net };
}
