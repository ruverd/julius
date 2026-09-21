import { expect, test } from "bun:test";
import { compareModeledCosts, priceUsage, type PriceSnapshot, type PricedUsage } from "../src/pricing";

const snapshot: PriceSnapshot = { id: "price-1", modelId: "m", providerId: "p", source: "user", effectiveAt: "2026-09-21T00:00:00Z", currency: "USD", tier: "standard", ratesPerMillion: { inputUncached: 1, cacheRead: 0.1, cacheWrite: 2, output: 4 } };
const usage: PricedUsage = { callId: "call-1", modelId: "m", providerId: "p", inputTokens: 1000, cacheReadTokens: 500, cacheWriteTokens: 100, outputTokens: 200, priceSnapshotId: "price-1" };
const baseline = { id: "baseline-1", evidence: "controlled_experiment" as const, modeledCostUsd: 0.001, comparisonScope: "same-task-pair" };

test("separate cache tiers can make a compressed request more expensive", () => {
  const uncompressed = priceUsage({ ...usage, inputTokens: 1000, cacheReadTokens: 1000, cacheWriteTokens: 0, outputTokens: 0 }, snapshot);
  const compressed = priceUsage({ ...usage, callId: "compressed", inputTokens: 500, cacheReadTokens: 0, cacheWriteTokens: 500, outputTokens: 0 }, snapshot);
  expect(uncompressed.modeledCostUsd).toBe(0.0001);
  expect(compressed.modeledCostUsd).toBe(0.001);
  expect(compareModeledCosts({ ...baseline, modeledCostUsd: uncompressed.modeledCostUsd }, [compressed]).netModeledSavingsUsd).toBeCloseTo(-0.0009);
});

test("unknown model, missing rate, and unknown counters remain unavailable", () => {
  expect(priceUsage({ ...usage, modelId: null }, snapshot).modeledCostUsd).toBeNull();
  expect(priceUsage({ ...usage, inputTokens: null }, snapshot).modeledCostUsd).toBeNull();
  expect(priceUsage(usage, { ...snapshot, ratesPerMillion: { ...snapshot.ratesPerMillion, cacheWrite: null } }).modeledCostUsd).toBeNull();
  expect(priceUsage({ ...usage, cacheWriteTokens: 0 }, { ...snapshot, ratesPerMillion: { ...snapshot.ratesPerMillion, cacheWrite: null } }).modeledCostUsd).not.toBeNull();
});

test("auxiliary calls and explicit overhead count once, with duplicate IDs rejected", () => {
  const primary = { callId: "primary", modeledCostUsd: 0.0004, priceSnapshotId: "price-1" };
  const auxiliary = { callId: "aux", modeledCostUsd: 0.0002, priceSnapshotId: "price-1" };
  const result = compareModeledCosts(baseline, [primary, auxiliary], [{ id: "cpu", kind: "local", costUsd: 0.0001 }, { id: "network", kind: "external", costUsd: 0.0001 }]);
  expect(result.netModeledSavingsUsd).toBeCloseTo(0.0002);
  expect(() => compareModeledCosts(baseline, [primary, primary])).toThrow("duplicate call ID");
  expect(compareModeledCosts(baseline, [{ ...primary, modeledCostUsd: null }]).netModeledSavingsUsd).toBeNull();
});

test("missing rate keys cannot become a free tier", () => {
  const malformed = { ...snapshot, ratesPerMillion: { inputUncached: 1, cacheRead: 0.1, output: 4 } } as unknown as PriceSnapshot;
  expect(() => priceUsage(usage, malformed)).toThrow("Invalid price rate");
  expect(() => priceUsage(usage, { ...snapshot, ratesPerMillion: { ...snapshot.ratesPerMillion, output: Number.POSITIVE_INFINITY } })).toThrow("Invalid price rate");
});

test("empty coverage and nonfinite aggregate are unavailable or rejected", () => {
  expect(compareModeledCosts(baseline, []).netModeledSavingsUsd).toBeNull();
  expect(compareModeledCosts(baseline, [], [], true).netModeledSavingsUsd).toBe(0.001);
  expect(() => compareModeledCosts(baseline, [
    { callId: "a", modeledCostUsd: Number.MAX_VALUE, priceSnapshotId: null },
    { callId: "b", modeledCostUsd: Number.MAX_VALUE, priceSnapshotId: null },
  ])).toThrow("overflow");
});
