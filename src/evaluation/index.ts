/** Import provider observations without equating local token estimates with usage. */
export interface Trial {
  task: string;
  repetition: number;
  arm: 'trail' | 'julius';
  revision: string;
  taskRevision: string;
  host: string;
  model: string;
  outcome: 'pass' | 'fail' | 'timeout';
  usage: { inputTokens: number | null; cachedInputTokens: number | null; outputTokens: number | null; costUsd: number | null };
}
export interface TrialSummary {
  runs: number; successes: number; successRate: number;
  totalTokens: number | null; costUsd: number | null; costPerSuccessUsd: number | null;
  usageCoverage: { tokens: number; cost: number };
}
function numeric(value: unknown, integer: boolean): value is number | null {
  return value === null || typeof value === 'number' && Number.isFinite(value) && value >= 0 && (!integer || Number.isSafeInteger(value));
}
export function validateTrials(value: unknown): Trial[] {
  if (!Array.isArray(value) || value.length === 0 || value.length > 10000) throw new Error('Expected 1–10000 trial records');
  const seen = new Set<string>(); const revisions = new Map<string, string>();
  for (const trial of value) {
    if (!trial || !['trail', 'julius'].includes(trial.arm) || !['pass', 'fail', 'timeout'].includes(trial.outcome)) throw new Error('Invalid arm or outcome');
    for (const field of ['task', 'revision', 'taskRevision', 'host', 'model']) if (typeof trial[field] !== 'string' || !trial[field].trim()) throw new Error(`Missing ${field}`);
    if (!Number.isSafeInteger(trial.repetition) || trial.repetition < 0) throw new Error('Invalid repetition');
    const key = JSON.stringify([trial.task, trial.repetition, trial.arm]);
    if (seen.has(key)) throw new Error('Duplicate task/repetition/arm'); seen.add(key);
    if (revisions.has(trial.arm) && revisions.get(trial.arm) !== trial.revision) throw new Error('Each arm must pin one executable revision');
    revisions.set(trial.arm, trial.revision);
    const u = trial.usage;
    if (!u || !numeric(u.inputTokens, true) || !numeric(u.cachedInputTokens, true) || !numeric(u.outputTokens, true) || !numeric(u.costUsd, false)) throw new Error('Usage requires nonnegative observations or explicit null');
    if (u.inputTokens !== null && u.cachedInputTokens !== null && u.cachedInputTokens > u.inputTokens) throw new Error('Cached input is a subset of total input');
  }
  return value as Trial[];
}
function summarize(records: Trial[]): TrialSummary {
  const tokens = records.map(r => r.usage.inputTokens === null || r.usage.outputTokens === null ? null : r.usage.inputTokens + r.usage.outputTokens);
  const costs = records.map(r => r.usage.costUsd);
  const sum = (values: Array<number | null>) => values.some(v => v === null) ? null : values.reduce<number>((a, b) => a + b!, 0);
  const costUsd = sum(costs); const successes = records.filter(r => r.outcome === 'pass').length;
  return { runs: records.length, successes, successRate: successes / records.length, totalTokens: sum(tokens), costUsd,
    costPerSuccessUsd: costUsd === null || successes === 0 ? null : costUsd / successes,
    usageCoverage: { tokens: tokens.filter(t => t !== null).length, cost: costs.filter(c => c !== null).length } };
}
export function compareTrials(input: unknown) {
  const trials = validateTrials(input);
  const baseline = trials.filter(t => t.arm === 'trail'); const candidate = trials.filter(t => t.arm === 'julius');
  const pairs = new Map(baseline.map(t => [JSON.stringify([t.task, t.repetition]), t]));
  if (!baseline.length || baseline.length !== candidate.length) throw new Error('Matched Trail and Julius trials required');
  for (const t of candidate) {
    const b = pairs.get(JSON.stringify([t.task, t.repetition]));
    if (!b || b.taskRevision !== t.taskRevision || b.host !== t.host || b.model !== t.model) throw new Error('Pair must use the same task snapshot, model and host');
  }
  const trail = summarize(baseline); const julius = summarize(candidate);
  const reduction = (a: number | null, b: number | null) => a === null || b === null || a === 0 ? null : 1 - b / a;
  return { method: 'Imported provider observations; not independently verified usage. Cached input is included in inputTokens. All attempts, including failures, must be included by the importer.',
    trail, julius, tokenReduction: reduction(trail.totalTokens, julius.totalTokens), costReduction: reduction(trail.costUsd, julius.costUsd), successDifference: julius.successRate - trail.successRate,
    statisticalConclusion: null, limitation: 'Descriptive paired totals only; no confidence interval or quality non-inferiority claim.' };
}
