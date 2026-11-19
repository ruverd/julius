import { ask, parseSpan, type AskHit } from '../ask/ask.js';
import { tokenize } from '../ask/index-file.js';
import { Economy, ECONOMY_MAX_BYTES, economyTokens, type RetainedRange } from '../economy/index.js';
import type { DeliveryChoice } from '../economy/delivery.js';
import { ensureFreshGraph } from '../graph/refresh.js';
import { pathUnderPrefix } from '../graph/scopes.js';
import { MAX_FILE_BYTES } from '../ingest/fs.js';
import { liveLearnings } from '../notes/learning-fields.js';
import { findNotes, listCheckoutNotes, notePlace, type Note } from '../notes/notes.js';
import { normalizePathPrefix } from '../util/paths.js';
import { readScopedSource } from '../util/source.js';

interface Span {
  kind: 'code' | 'note';
  path: string;
  first: number;
  lines: string[];
  heading?: string;
  anchors?: Array<{ from: number; to: number; name: string }>;
}

function codeSpans(root: string, hits: AskHit[]): Span[] {
  const files = new Map<string, Span & Required<Pick<Span, 'anchors'>>>();
  let bytes = 0;
  for (const hit of hits) {
    const range = parseSpan(hit.pointer);
    // File nodes have a bare path; concepts and unresolved imports don't.
    const path = range?.path ?? (hit.kind === 'symbol' ? hit.pointer : undefined);
    if (!path) continue;
    let file = files.get(path);
    if (!file) {
      const text = readScopedSource(root, path, MAX_FILE_BYTES);
      if (!text) continue;
      bytes += Buffer.byteLength(text);
      if (bytes > ECONOMY_MAX_BYTES) throw new Error('Repository evidence exceeds the local capture limit; narrow the query or lower the limit');
      const lines = text.split('\n');
      if (lines.at(-1) === '') lines.pop();
      file = { kind: 'code', path, first: 1, lines, anchors: [] };
      files.set(path, file);
    }
    if (range) file.anchors.push({ ...range, name: hit.title.split(' · ', 1)[0]! });
  }
  return [...files.values()];
}

function noteSpans(notes: Note[]): Span[] {
  const seen = new Set<string>();
  const spans: Span[] = [];
  for (const note of notes) {
    const path = notePlace(note);
    const lines = note.body.split('\n');
    const touches = [...new Set(note.touches)].sort();
    let heading: string | undefined;
    let first = 0;
    for (let end = 0; end <= lines.length; end++) {
      const row = lines[end];
      if (row !== undefined && !/^#{1,6}\s/.test(row)) continue;
      const section = lines.slice(first, end);
      // Repeated sections with the same stated scope carry the same claim.
      // Keep differing sections and sections from different scopes intact.
      const key = JSON.stringify([touches, heading, section.join('\n')]);
      if (section.some(line => line.trim()) && !seen.has(key)) {
        seen.add(key);
        spans.push({ kind: 'note', path, first: first + 1, lines: section, heading });
      }
      heading = row?.trimEnd();
      first = end + 1;
    }
  }
  return spans;
}

function renderSpan(span: Span, start: number, end: number): string {
  const first = span.first + start;
  const last = span.first + end - 1;
  const location = `L${first}${last > first ? `-L${last}` : ''}`;
  const heading = span.heading ? ` under ${JSON.stringify(span.heading)}` : '';
  return `${span.kind} ${JSON.stringify(span.path)} ${span.kind === 'note' ? 'body ' : ''}${location}${heading}\n`
    + span.lines.slice(start, end).map(line => `| ${line}`).join('\n');
}

interface Candidate {
  span: Span;
  index: number;
  start: number;
  end: number;
  terms: Set<string>;
  score: number;
}

function evidenceTerms(text: string): string[] {
  return tokenize(text).map(term => {
    if (term === 'size') return 'length';
    if (term === 'comparison') return 'compare';
    return term.length >= 4 && /[^s]s$/.test(term) ? term.slice(0, -1) : term;
  });
}

function rankPassages(spans: Span[], query: string): Candidate[] {
  const terms = new Set(evidenceTerms(query));
  const identifiers = new Set(query.toLowerCase().match(/[\w$]+/g) ?? []);
  const ranked: Candidate[] = [];
  for (const [position, span] of spans.entries()) {
    const matches = span.lines.map(line => new Set(evidenceTerms(line).filter(term => terms.has(term))));
    const pathMatches = new Set(evidenceTerms(span.path).filter(term => terms.has(term))).size;
    const candidates: Candidate[] = [];
    for (const [index, center] of matches.entries()) {
      if (!center.size) continue;
      const start = span.kind === 'code' ? Math.max(0, index - 1) : index;
      const end = span.kind === 'code' ? Math.min(span.lines.length, index + 2) : index + 1;
      const nearby = new Set(matches.slice(start, end).flatMap(line => [...line]));
      const anchors = span.anchors?.filter(({ from, to }) => from <= index + 1 && index + 1 <= to) ?? [];
      const named = anchors.some(anchor => identifiers.has(anchor.name.toLowerCase()));
      const decision = span.heading?.toLowerCase() === '## decided';
      const affinity = named ? 4 : Number(anchors.length > 0 || decision);
      const score = 2 * center.size + 1.5 * nearby.size + affinity + Math.min(3, pathMatches) + 1 / (position + 1);
      candidates.push({ span, index, start, end, terms: nearby, score });
    }
    candidates.sort((a, b) => b.score - a.score || a.index - b.index);
    ranked.push(...candidates.slice(0, 24));
  }
  return ranked.sort((a, b) => b.score - a.score).slice(0, 96);
}

function fitsBudget(text: string, budget: number): boolean {
  try { return economyTokens(text) <= budget; }
  catch (error) {
    if (error instanceof Error && error.message.startsWith('Exact token count unavailable')) return false;
    throw error;
  }
}

function preview(spans: Span[], query: string, budget: number, handle: string): string {
  const selected = new Map<Span, Set<number>>();
  const prefix = `Repository evidence\nMore evidence: context.read ${handle}`;
  const render = () => {
    const sections = [prefix];
    for (const span of spans) {
      const indices = [...(selected.get(span) ?? [])].sort((a, b) => a - b);
      for (let i = 0; i < indices.length; i++) {
        const start = indices[i]!;
        while (indices[i + 1] === indices[i]! + 1) i++;
        sections.push(renderSpan(span, start, indices[i]! + 1));
      }
    }
    return sections.join('\n\n');
  };
  let text = prefix;
  const ordered = rankPassages(spans, query);
  const remaining = [...ordered];
  const covered = new Set<string>();
  const usedPaths = new Set<string>();
  const usedKinds = new Set<Span['kind']>();
  const priority = (entry: Candidate) => entry.score
    + 1.5 * [...entry.terms].filter(term => !covered.has(term)).length
    + (usedPaths.has(entry.span.path) ? 0 : 2)
    + (usedKinds.has(entry.span.kind) ? 0 : 2);
  const quoteBudget = Math.max(0, budget - 35);
  const add = (span: Span, start: number, end: number, cap: number) => {
    const prior = selected.get(span) ?? new Set<number>();
    const additions = new Set(prior);
    for (let line = start; line < end; line++) additions.add(line);
    if (additions.size === prior.size || span.lines.slice(start, end).some(line => line.length > cap * 8)) return false;
    selected.set(span, additions);
    const trial = render();
    if (fitsBudget(trial, cap)) { text = trial; return true; }
    selected.set(span, prior);
    return false;
  };
  for (let count = 0; count < 48 && remaining.length; count++) {
    let best = 0;
    let score = -Infinity;
    for (const [index, entry] of remaining.entries()) {
      const current = priority(entry);
      if (current > score) { best = index; score = current; }
    }
    const [entry] = remaining.splice(best, 1);
    if (!entry) break;
    const { span, index, start, end } = entry;
    if (selected.get(span)?.has(index)) continue;
    if (add(span, start, end, quoteBudget) || add(span, index, index + 1, quoteBudget)) {
      for (const term of entry.terms) covered.add(term);
      usedPaths.add(span.path);
      usedKinds.add(span.kind);
    }
  }
  const nextPaths = new Set<string>();
  for (const { span, index, start, end } of ordered) {
    if (nextPaths.size === 2) break;
    if (nextPaths.has(span.path) || selected.get(span)?.has(index)) continue;
    const selector = { source: span.path, from: span.first + start, to: span.first + end - 1 };
    const trial = `${text}\nnext ${JSON.stringify(selector)}`;
    if (!fitsBudget(trial, budget)) continue;
    text = trial;
    nextPaths.add(span.path);
  }
  if (!usedPaths.size && !nextPaths.size && ordered[0]) {
    const { span, index } = ordered[0];
    add(span, index, index + 1, budget);
  }
  return text;
}

interface EvidenceLocation { source: string; from: number; to?: number }
export interface EvidenceSelector {
  source?: string;
  from?: number;
  to?: number;
  query?: string;
  limit?: number;
  exclude?: EvidenceLocation[];
}

const spanHeader = /^(code|note) ("(?:[^"\\]|\\.)*") (?:body )?L(\d+)(?:-L(\d+))?(?: under ("(?:[^"\\]|\\.)*"))?$/;

function retainedSpans(bytes: Buffer, source?: string) {
  const text = bytes.toString('utf8');
  if (!text.startsWith('Repository evidence\n\n')) throw new Error('Handle does not contain repository evidence');
  const spans: Span[] = [];
  const offsets = new Map<Span, Array<{ start: number; end: number }>>();
  let position = 0;
  let current: Span | undefined;
  for (const row of text.split('\n')) {
    const end = position + Buffer.byteLength(row);
    if (current && row.startsWith('| ')) {
      current.lines.push(row.slice(2));
      offsets.get(current)!.push({ start: position, end });
    } else {
      const match = spanHeader.exec(row);
      current = undefined;
      if (match && (!source || JSON.parse(match[2]!) === source)) {
        current = { kind: match[1] as Span['kind'], path: JSON.parse(match[2]!), first: Number(match[3]), lines: [],
          ...(match[5] ? { heading: JSON.parse(match[5]) as string } : {}),
        };
        spans.push(current);
        offsets.set(current, []);
      }
    }
    position = end + 1;
  }
  const range = (span: Span, start: number, end: number): RetainedRange => {
    const rows = offsets.get(span)!;
    return { start: rows[start]!.start, end: rows[end - 1]!.end,
      evidence: { path: span.path, kind: span.kind, from: span.first + start, to: span.first + end - 1,
        heading: span.heading && span.heading.length <= 160 ? span.heading : undefined,
      },
    };
  };
  return { spans, range };
}

export function resolveEvidenceRange(bytes: Buffer, selector: EvidenceSelector): RetainedRange {
  const { source, from, to = from } = selector;
  if (!source || from === undefined || to === undefined || to < from || selector.limit !== undefined || selector.exclude !== undefined) {
    throw new Error('Evidence read requires a source and a valid line range');
  }
  const { spans, range } = retainedSpans(bytes, source);
  const span = spans.find(span => span.first <= from && to < span.first + span.lines.length);
  if (!span) throw new Error('Requested evidence was not found in this snapshot');
  return range(span, from - span.first, to - span.first + 1);
}

export function searchEvidenceRanges(bytes: Buffer, selector: EvidenceSelector): RetainedRange[] {
  const { query, source, limit = 5, exclude = [] } = selector;
  if (!query?.trim() || selector.from !== undefined || selector.to !== undefined || exclude.some(item => (item.to ?? item.from) < item.from)) {
    throw new Error('Evidence search requires a query and valid exclusions');
  }
  const { spans, range } = retainedSpans(bytes, source);
  if (source && !spans.length) throw new Error('Requested evidence was not found in this snapshot');
  const claimed = [...exclude];
  const used = new Set<string>();
  const covered = new Set<string>();
  const contains = (span: Span, index: number) => claimed.some(item => item.source === span.path
    && item.from <= span.first + index && span.first + index <= (item.to ?? item.from));
  const ranked = rankPassages(spans, query);
  const priority = (entry: Candidate) => entry.score
    + (used.has(entry.span.path) ? 0 : 4)
    + 2 * [...entry.terms].filter(term => !covered.has(term)).length;
  const results: RetainedRange[] = [];
  for (let count = 0; count < limit; count++) {
    let best: Candidate | undefined;
    let bestPriority = -Infinity;
    for (const entry of ranked) {
      if (contains(entry.span, entry.index)) continue;
      const score = priority(entry);
      if (score > bestPriority) { best = entry; bestPriority = score; }
    }
    if (!best) break;
    const { span, index } = best;
    let start = index;
    let end = index + 1;
    while (start > best.start && !contains(span, start - 1)) start--;
    while (end < best.end && !contains(span, end)) end++;
    const result = range(span, start, end);
    results.push(result);
    claimed.push({ source: span.path, from: result.evidence.from, to: result.evidence.to });
    used.add(span.path);
    for (const term of best.terms) covered.add(term);
  }
  return results;
}

export async function deliverContextEvidence(
  root: string,
  args: { query: string; limit?: number; in?: string },
  choice: DeliveryChoice,
  dir?: string,
): Promise<string> {
  await ensureFreshGraph(root, { contextDir: dir });
  const result = ask(root, args.query, { contextDir: dir, limit: args.limit ?? 5, in: args.in });
  const code = codeSpans(root, result.hits);
  const prefix = normalizePathPrefix(args.in ?? '');
  const live = liveLearnings(listCheckoutNotes(root));
  const scoped = prefix ? live.filter(note => note.touches.some(touch => pathUnderPrefix(touch.split('#')[0]!, prefix))) : live;
  const ranked = findNotes(scoped, args.query, code.map(span => span.path), 8);
  const spans = [...noteSpans(ranked.map(({ note }) => note)), ...code];
  const archive = spans.length
    ? ['Repository evidence', ...spans.map(span => renderSpan(span, 0, span.lines.length))].join('\n\n')
    : 'No repository evidence matched.';
  const economy = new Economy(root);
  if (choice.algorithm !== 'fixed') return (await economy.present(archive, choice, 'mcp')).text;
  const budget = choice.budget ?? 1200;
  return (await economy.capture(archive, { budget, transport: 'mcp', preview: handle => preview(spans, args.query, budget, handle) })).text;
}
