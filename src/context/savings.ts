/** Counterfactual graph comparisons. Separate from the Economy payload ledger. */
import type { GraphV1 } from '../graph/types.js';
import { tag } from "../brand.js";

export interface Savings {
  /** How many source files the baseline covers. */
  files: number;
  /** Total chars of those files — the "read them whole" cost. */
  baselineChars: number;
}

/** Rough tokens for a byte length (≈ 4 chars/token; good enough for an estimate). */
export function toTokens(chars: number): number {
  return Math.round(chars / 4);
}

/** path → char size, from the file nodes the build sized. Skips nodes with no
 * `chars` (pre-upgrade graphs), so an old index just yields a smaller baseline
 * rather than a wrong one. */
function fileSizes(graph: GraphV1): Map<string, number> {
  const m = new Map<string, number>();
  for (const n of graph.nodes)
    if (n.kind === 'file' && typeof n.chars === 'number') m.set(n.path, n.chars);
  return m;
}

/** Baseline = whole size of the distinct `paths`, summed from file-node sizes.
 * Returns undefined when not a single path has a known size — the caller then
 * omits the estimate instead of claiming a bogus one. */
export function savingsFor(graph: GraphV1, paths: Iterable<string>): Savings | undefined {
  const sizes = fileSizes(graph);
  let baselineChars = 0;
  let files = 0;
  for (const p of new Set(paths)) {
    const c = sizes.get(p);
    if (c === undefined) continue;
    baselineChars += c;
    files++;
  }
  return files > 0 ? { files, baselineChars } : undefined;
}

/** Compatibility setter. Counterfactual graph estimates must never be priced as billing. */
export function setInputRate(_usdPerMtok: number | null): void {}

/** Kept for callers compiled against the previous API; never steer promotional replies. */
export function savingsTurnNudge(_savedTokens: number): string { return ''; }

/** A full-file-read counterfactual, separate from the measured Economy ledger.
 * Negative differences are meaningful: a graph answer can cost more than a file. */
export function savingsLine(body: string, saved: Savings | undefined): string {
  if (!saved) return '';
  const pack = toTokens(body.length), base = toTokens(saved.baselineChars);
  return `${tag()} counterfactual full-file-read difference ≈ ${base - pack} tokens ` +
    `(chars/4 estimate: ${base} source vs ${pack} output; ${saved.files} files). Not measured usage or billing.`;
}

/** Parse historical hook/session footers only. New graph outputs do not emit these. */
export function sumSavingsFooters(text: string): number {
  let total = 0;
  // The code a query saved reading, and the digging a reused learning saved.
  for (const m of text.matchAll(/\[(?:julius)\] (?:tokens|learnings) saved ≈ ([\d,]+)/g)) {
    total += Number(m[1].replace(/,/g, '')) || 0;
  }
  return total;
}

/** Keep the estimate distinct from the source body. */
export function withSavings(body: string, saved: Savings | undefined): string {
  const line = savingsLine(body, saved);
  return line ? `${line}\n\n${body}` : body;
}
