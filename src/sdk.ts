import { join } from 'node:path';
import { ArtifactStore } from './artifacts';
import { Ledger } from './ledger';
import { optimize, type OptimizationContext } from './optimizer';
import type { OptimizationPolicy } from './policy';
import type { EconomyEvent } from './events';
import { report } from './reporting';
import { queryWindow } from './query';

export class Julius {
  readonly ledger: Ledger;
  readonly artifacts: ArtifactStore;
  constructor(directory: string) {
    this.artifacts = new ArtifactStore(join(directory, 'artifacts'));
    this.ledger = new Ledger(join(directory, 'ledger.sqlite'));
  }
  optimize(context: OptimizationContext, policy: OptimizationPolicy) {
    const eligibility = optimize({ ...context, recovery: undefined }, policy);
    if (eligibility.receipt.reason !== 'recovery_required') return { ...eligibility, original: null };
    const original = this.artifacts.put(context.projectId, context.content);
    const result = optimize({ ...context, recovery: { artifactId: original.id, available: true } }, policy);
    if (!result.receipt.applied) {
      this.artifacts.delete(context.projectId, original.id);
      return { ...result, original: null };
    }
    return { ...result, original };
  }
  recordUsage(event: Extract<EconomyEvent, { eventType: 'usage' }>) { return this.ledger.record(event); }
  recordOutcome(event: Extract<EconomyEvent, { eventType: 'outcome' }>) { return this.ledger.record(event); }
  report(query: { since?: string; until?: string; projectId?: string; taskId?: string; modelId?: string } = {}) {
    const window = queryWindow(query);
    return report(this.ledger.events({ ...query, since: window.since, until: window.until }), window);
  }
  close() { this.ledger.close(); }
}
export { optimize } from './optimizer';
export type { OptimizationContext, OptimizationReceipt } from './optimizer';
export type { OptimizationPolicy } from './policy';
export type { EconomyEvent, Evidence } from './events';
export { MemoryStore } from './memory';
export type { MemoryItem, MemoryHit } from './memory';
export { priceUsage, compareModeledCosts } from './pricing';
export type { PriceSnapshot, PricedUsage, ComparableBaseline } from './pricing';
