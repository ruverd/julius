import { ask, parseSpan, type AskHit } from '../ask/ask.js';
import { tokenize } from '../ask/index-file.js';
import { Economy, ECONOMY_MAX_BYTES, economyTokens } from '../economy/index.js';
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
  anchors?: Array<{ from: number; to: number }>;
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
    if (range) file.anchors.push(range);
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

interface Candidate { span: Span; index: number; matches: number; anchor: boolean }

function prioritizedLines(spans: Span[], query: string): Candidate[] {
  const terms = new Set(tokenize(query));
  const firstCode: Candidate[] = [];
  const firstNote: Candidate[] = [];
  const rest: Candidate[] = [];
  for (const span of spans) {
    const lines = span.lines.flatMap((line, index) => line.trim() ? [{ span, index,
      matches: new Set(tokenize(line).filter(term => terms.has(term))).size,
      anchor: span.anchors?.some(({ from, to }) => from <= index + 1 && index + 1 <= to) ?? false,
    }] : []);
    lines.sort((a, b) => b.matches - a.matches || Number(b.anchor) - Number(a.anchor) || a.index - b.index);
    const best = lines.shift();
    if (!best) continue;
    (span.kind === 'code' ? firstCode : firstNote).push(best);
    rest.push(...lines.slice(0, 16));
  }
  const leaders: Candidate[] = [];
  for (let i = 0; i < Math.max(firstCode.length, firstNote.length); i++) {
    if (firstCode[i]) leaders.push(firstCode[i]!);
    if (firstNote[i]) leaders.push(firstNote[i]!);
  }
  return [...leaders, ...rest.sort((a, b) => b.matches - a.matches)].slice(0, 256);
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
  for (const { span, index } of prioritizedLines(spans, query)) {
    if (span.lines[index]!.length > budget * 8) continue;
    const indices = selected.get(span) ?? new Set<number>();
    selected.set(span, indices);
    indices.add(index);
    const candidate = render();
    let fits = false;
    try { fits = economyTokens(candidate) <= budget; }
    catch (error) {
      if (!(error instanceof Error && error.message.startsWith('Exact token count unavailable'))) throw error;
    }
    if (fits) text = candidate;
    else indices.delete(index);
  }
  return text;
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
