import { createHash } from 'node:crypto';
import { closeSync, constants, fstatSync, openSync, readFileSync, realpathSync } from 'node:fs';
import { isAbsolute, join, relative, resolve } from 'node:path';
import { contextDirFor } from '../context/node-file.js';
import { buildGraph } from '../graph/build.js';
import { readFingerprint } from '../graph/fingerprint.js';
import { listSourceFiles } from '../graph/source-files.js';
import { readGraph, wiringPath } from '../graph/write.js';
import { WALK_RELATIONS } from '../graph/relations.js';
import type { EdgeV1, GraphV1, NodeV1 } from '../graph/types.js';
import { readWorkspace } from '../graph/workspace.js';
import { contentHash } from '../util/id.js';
import { walkDir } from '../ingest/fs.js';
import { readBuildConfig, readFollowNestedRepos, readFollowSubmodules, readIncludeDirs } from '../util/state.js';
import { Economy, economyTokens } from '../economy/index.js';
import type { DeliveryChoice } from '../economy/delivery.js';

export interface InvestigationArgs {
  recipe: 'change-impact' | 'failure-localization';
  paths?: string[];
  query?: string;
  depth?: number;
}
interface Snapshot { id: string; sources: Map<string, string>; hashes: Record<string, string>; onlyDirs?: string[] }
export interface Evidence {
  id: string; path: string; span: string; kind: string; name: string;
  role: 'seed' | 'dependent' | 'match'; depth: number;
  via?: { source: string; target: string; relation: string; confidence: string };
  excerpt: string; excerptComplete: boolean;
  symbol?: { id: string; name: string; span: string };
}
export interface InvestigationReport {
  version: 1; recipe: InvestigationArgs['recipe']; snapshot: string; graphRevision: string;
  coverage: { scope: string; indexedFiles: number; sourceFiles: number; unindexedFiles: number; traversalComplete: boolean };
  unknowns: string[]; evidence: Evidence[]; reused: boolean;
}
const MAX_SOURCES = 10000;
const MAX_SOURCE_BYTES = 32 * 1024 * 1024;
const MAX_GRAPH_NODES = 100000;
const MAX_GRAPH_EDGES = 300000;
const MAX_VISITS = 10000;
const MAX_EVIDENCE = 500;
const MAX_CACHE_BYTES = 8 * 1024 * 1024;
const cache = new Map<string, string>();
let cacheBytes = 0;
const queues = new Map<string, Promise<void>>();
const sha = (text: string) => createHash('sha256').update(text).digest('hex');

function safeRead(root: string, path: string): Buffer {
  const rel = relative(root, realpathSync(path));
  if (isAbsolute(rel) || rel === '..' || rel.startsWith('../') || rel.startsWith('..\\')) throw new Error('Source escapes repository');
  const fd = openSync(path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0) | (constants.O_NONBLOCK ?? 0));
  try {
    const stat = fstatSync(fd);
    if (!stat.isFile() || stat.size > 1024 * 1024) throw new Error('Unsupported source file or source exceeds 1 MiB');
    return readFileSync(fd);
  } finally { closeSync(fd); }
}
function decode(bytes: Buffer): string | null {
  if (bytes[0] === 0xfe && bytes[1] === 0xff) return null;
  return bytes[0] === 0xff && bytes[1] === 0xfe ? bytes.subarray(2).toString('utf16le') : bytes.toString('utf8');
}
function snapshot(root: string, out: string): Snapshot {
  const onlyDirs = readFingerprint(out)?.onlyDirs;
  const repoFiles = walkDir(root);
  const sharedWalk = !readIncludeDirs(root)?.size && !readFollowSubmodules(root) && !readFollowNestedRepos(root);
  const files = listSourceFiles(root, out, sharedWalk ? repoFiles : undefined, onlyDirs ? new Set(onlyDirs) : undefined).sort();
  if (files.length > MAX_SOURCES) throw new Error('Investigation source limit exceeded; use ordinary graph tools with a narrower scope');
  const sources = new Map<string, string>(); const hashes: Record<string, string> = Object.create(null);
  let bytes = 0;
  for (const file of files) {
    const raw = safeRead(root, file); bytes += raw.length;
    if (bytes > MAX_SOURCE_BYTES) throw new Error('Investigation exceeds 32 MiB of source; use scoped graph tools');
    const path = relative(root, file).replaceAll('\\', '/'); const text = decode(raw);
    if (text === null) throw new Error(`Unsupported source encoding: ${path}`);
    sources.set(path, text); hashes[path] = contentHash(text);
  }
  // Configuration can affect resolution without changing a matched source file.
  const config: Array<[string, string]> = [];
  for (const file of repoFiles.filter(p => /(?:^|[/\\])(?:package(?:-lock)?\.json|tsconfig[^/\\]*\.json|jsconfig\.json|go\.(?:mod|sum)|Cargo\.(?:toml|lock)|\.gitignore)$/.test(p)).sort()) {
    const raw = safeRead(root, file); bytes += raw.length;
    if (bytes > MAX_SOURCE_BYTES) throw new Error('Investigation snapshot exceeds byte limit');
    config.push([relative(root, file), sha(raw.toString('base64'))]);
  }
  return { id: sha(JSON.stringify({ hashes, config, onlyDirs, buildConfig: readBuildConfig(root) })), sources, hashes, onlyDirs };
}
function graphMatches(snapshot: Snapshot, out: string): boolean {
  const fp = readFingerprint(out);
  return !!fp && Object.keys(fp.files).length === snapshot.sources.size &&
    Object.entries(snapshot.hashes).every(([path, hash]) => fp.files[path]?.[2] === hash);
}
function validateArgs(args: InvestigationArgs): void {
  if (!['change-impact', 'failure-localization'].includes(args.recipe)) throw new Error('Unknown investigation recipe');
  if (args.recipe === 'change-impact' && (!args.paths?.length || args.query !== undefined)) throw new Error('change-impact requires paths and does not accept query');
  if (args.recipe === 'failure-localization' && (!args.query?.trim() || args.paths !== undefined)) throw new Error('failure-localization requires a literal query and does not accept paths');
  if (args.query !== undefined && (typeof args.query !== 'string' || args.query.length > 512)) throw new Error('query exceeds 512 characters');
  if (args.depth !== undefined && (!Number.isInteger(args.depth) || args.depth < 1 || args.depth > 8)) throw new Error('depth must be 1 through 8');
  if (args.paths !== undefined && (!Array.isArray(args.paths) || args.paths.length > 32 || args.paths.some(p => typeof p !== 'string' || p.length > 4096 || !p || isAbsolute(p) || p.includes('\\') || p.split('/').some(s => s === '..' || s === '.' || s === '') || /^[A-Za-z]:/.test(p)))) throw new Error('paths must be up to 32 exact repository-relative paths');
}
function evidence(node: NodeV1, sources: Map<string, string>, role: Evidence['role'], depth: number, via?: EdgeV1): Evidence {
  const span = /^L(\d+)-L(\d+)$/.exec(node.span);
  const lines = (sources.get(node.path) ?? '').split('\n');
  const start = span ? Number(span[1]) - 1 : 0;
  const end = span ? Number(span[2]) : start;
  const excerpt = lines.slice(start, Math.min(end, start + 12)).join('\n').slice(0, 2000);
  return { id: node.id, path: node.path, span: node.span, kind: node.kind, name: node.name, role, depth,
    ...(via ? { via: { ...via } } : {}), excerpt, excerptComplete: end - start <= 12 && lines.slice(start, end).join('\n').length <= 2000 };
}

export function investigateGraph(graph: GraphV1, state: Snapshot, args: InvestigationArgs): InvestigationReport {
  validateArgs(args);
  if (graph.nodes.length > MAX_GRAPH_NODES || graph.edges.length > MAX_GRAPH_EDGES) throw new Error('Investigation graph limit exceeded');
  const deadline = Date.now() + 5000;
  const byId = new Map(graph.nodes.map(n => [n.id, n]));
  const indexed = new Set(graph.nodes.filter(n => n.kind === 'file').map(n => n.path));
  const unknowns = ['Structural evidence is not a complete program analysis; dynamic dispatch, ignored files and unsupported syntax may be missing. No matches does not prove no impact.'];
  const report: InvestigationReport = { version: 1, recipe: args.recipe, snapshot: state.id, graphRevision: sha(JSON.stringify(graph)),
    coverage: { scope: state.onlyDirs?.join(', ') || 'repository source selection', indexedFiles: indexed.size, sourceFiles: state.sources.size, unindexedFiles: [...state.sources.keys()].filter(p => !indexed.has(p)).length, traversalComplete: true },
    unknowns, evidence: [], reused: false };
  if (args.recipe === 'failure-localization') {
    const query = args.query!;
    const symbols = new Map<string, Array<{ node: NodeV1; start: number; end: number }>>();
    for (const node of graph.nodes) {
      const span = /^L(\d+)-L(\d+)$/.exec(node.span);
      if (node.kind === 'file' || !span) continue;
      const entries = symbols.get(node.path) ?? [];
      entries.push({ node, start: Number(span[1]), end: Number(span[2]) }); symbols.set(node.path, entries);
    }
    for (const entries of symbols.values()) entries.sort((a, b) => (a.end - a.start) - (b.end - b.start));
    for (const [path, text] of state.sources) {
      const lines = text.split('\n');
      for (let i = 0; i < lines.length; i++) {
        if (Date.now() > deadline || report.evidence.length >= MAX_EVIDENCE) { report.coverage.traversalComplete = false; break; }
        if (!lines[i].includes(query)) continue;
        const owner = symbols.get(path)?.find(s => s.start <= i + 1 && s.end >= i + 1)?.node;
        report.evidence.push({ ...(owner ? { symbol: { id: owner.id, name: owner.name, span: owner.span } } : {}), id: `${path}:L${i + 1}`, path, span: `L${Math.max(1, i)}-L${Math.min(lines.length, i + 2)}`, kind: 'source-match', name: query, role: 'match', depth: 0, excerpt: lines.slice(Math.max(0, i - 1), i + 2).join('\n').slice(0, 2000), excerptComplete: lines.slice(Math.max(0, i - 1), i + 2).join('\n').length <= 2000 });
      }
      if (!report.coverage.traversalComplete) break;
    }
    unknowns.push('Literal diagnostic matches are candidates, not verified root causes.');
  } else {
    const paths = new Set(args.paths);
    for (const path of paths) if (!indexed.has(path)) unknowns.push(`No indexed file for ${path}; deleted, excluded or unsupported source needs direct inspection.`);
    const seeds = graph.nodes.filter(n => paths.has(n.path));
    const incoming = new Map<string, EdgeV1[]>();
    for (const edge of graph.edges) if (WALK_RELATIONS.has(edge.relation)) {
      const list = incoming.get(edge.target) ?? []; list.push(edge); incoming.set(edge.target, list);
    }
    const seen = new Set(seeds.map(n => n.id));
    let frontier = seeds.map(n => n.id);
    for (const node of seeds) {
      if (report.evidence.length >= MAX_EVIDENCE) { report.coverage.traversalComplete = false; break; }
      report.evidence.push(evidence(node, state.sources, 'seed', 0));
    }
    for (let depth = 1; depth <= (args.depth ?? 2) && frontier.length && report.coverage.traversalComplete; depth++) {
      const next: string[] = [];
      for (const id of frontier) for (const edge of incoming.get(id) ?? []) {
        if (Date.now() > deadline || seen.size >= MAX_VISITS || report.evidence.length >= MAX_EVIDENCE) { report.coverage.traversalComplete = false; break; }
        if (seen.has(edge.source)) continue;
        seen.add(edge.source); next.push(edge.source);
        const node = byId.get(edge.source);
        if (node) report.evidence.push(evidence(node, state.sources, 'dependent', depth, edge));
        else unknowns.push(`Unresolved graph endpoint: ${edge.source}`);
      }
      frontier = next;
    }
    unknowns.push(`Impact traversal is limited to ${args.depth ?? 2} incoming hops; dependents are candidates, not proven breakages.`);
  }
  if (!report.coverage.traversalComplete) unknowns.push('Investigation reached an execution or evidence limit; omitted results require narrower investigation.');
  return report;
}

async function execute(root: string, args: InvestigationArgs, dir?: string): Promise<InvestigationReport> {
  validateArgs(args);
  root = realpathSync(root); const out = contextDirFor(root, dir);
  if (readWorkspace(root, dir)) throw new Error('Investigations require one repository; use the existing federated graph tools for workspace roots');
  let before = snapshot(root, out);
  let graph = readGraph(wiringPath(out));
  const contextKey = `${root}\0${resolve(out)}\0`;
  // Full snapshot equality, not mtime, gates reuse. A changed configuration also rebuilds.
  const knownSnapshot = [...cache.keys()].some(k => k.startsWith(`${contextKey}${before.id}\0`));
  if (!graph || !graphMatches(before, out) || !knownSnapshot) {
    const disabled = process.env.JULIUS_NO_REFRESH;
    if (disabled && disabled !== '0' && disabled !== 'false') throw new Error('Investigation requires verified indexing but automatic refresh is disabled; use direct source tools');
    await buildGraph(root, { contextDir: dir, graphOnly: true, onlyDirs: before.onlyDirs });
    graph = readGraph(wiringPath(out));
    const afterBuild = snapshot(root, out);
    if (before.id !== afterBuild.id) throw new Error('Repository changed during investigation indexing; retry the investigation');
    before = afterBuild;
  }
  if (!graph || !graphMatches(before, out)) throw new Error('Cannot verify graph against current source; use direct inspection');
  const key = `${contextKey}${before.id}\0${sha(JSON.stringify(graph))}\0${JSON.stringify(args)}`;
  const saved = cache.get(key);
  const report: InvestigationReport = saved ? { ...JSON.parse(saved), reused: true } : investigateGraph(graph, before, args);
  if (snapshot(root, out).id !== before.id) throw new Error('Repository changed during investigation; result discarded, retry');
  if (!saved) {
    const text = JSON.stringify(report); const size = Buffer.byteLength(text);
    if (size <= MAX_CACHE_BYTES) {
      while (cache.size >= 32 || cacheBytes + size > MAX_CACHE_BYTES) {
        const first = cache.keys().next().value!; cacheBytes -= Buffer.byteLength(cache.get(first)!); cache.delete(first);
      }
      cache.set(key, text); cacheBytes += size;
    }
  }
  return report;
}

export async function runInvestigation(root: string, args: InvestigationArgs, dir?: string): Promise<InvestigationReport> {
  const key = `${realpathSync(root)}\0${contextDirFor(root, dir)}`;
  const previous = queues.get(key) ?? Promise.resolve();
  let release!: () => void;
  const current = new Promise<void>(done => { release = done; });
  const tail = previous.then(() => current); queues.set(key, tail);
  await previous;
  try { return await execute(root, args, dir); }
  finally { release(); if (queues.get(key) === tail) queues.delete(key); }
}

export async function deliverInvestigation(root: string, report: InvestigationReport, budgetOrChoice: number | DeliveryChoice): Promise<string> {
  const choice: DeliveryChoice = typeof budgetOrChoice === 'number'
    ? { algorithm: 'fixed', label: 'fixed', budget: budgetOrChoice, literals: [] }
    : budgetOrChoice;
  const full = JSON.stringify(report);
  const economy = new Economy(root);
  if (choice.algorithm === 'full') return (await economy.present(full, choice, 'mcp')).text;
  const budget = choice.budget ?? 1200;
  const ranked = [...report.evidence].sort((a, b) => Number(b.role !== 'seed') - Number(a.role !== 'seed') || a.depth - b.depth || a.id.localeCompare(b.id));
  const pool = choice.literals.length > 0
    ? ranked.filter(item => choice.literals.some(literal => [item.path, item.name, item.id, item.excerpt].some(field => field.includes(literal))))
    : ranked;
  const recover = (handle: string) => ({ operation: 'context.read', args: { handle }, instruction: 'Search a path or read byte ranges through julius_call; no user command needed.' });
  const handle = economy.hold(full);
  const rawTokens = (() => { try { return economyTokens(full); } catch { return null; } })();
  if (rawTokens !== null) {
    const complete = JSON.stringify({ ...report, evidence: ranked, omittedEvidence: 0, handle, delivery: choice.label, recover: recover(handle) });
    if (economyTokens(complete) <= budget) {
      economy.recordDelivery(rawTokens, economyTokens(complete));
      return complete;
    }
  }
  if (choice.literals.length > 0 && pool.length === 0) {
    const text = JSON.stringify({ ...report, evidence: [], omittedEvidence: ranked.length, match: false, handle, delivery: choice.label, next: { start: 0, end: Buffer.byteLength(full) }, recover: recover(handle) });
    if (economyTokens(text) <= budget) { economy.recordDelivery(rawTokens, economyTokens(text)); return text; }
    return (await economy.present(full, choice, 'mcp')).text;
  }
  let count = pool.length;
  while (count >= 0) {
    const text = JSON.stringify({ ...report, evidence: pool.slice(0, count), omittedEvidence: ranked.length - count, handle, delivery: choice.label, recover: recover(handle) });
    let fits = false;
    try { fits = economyTokens(text) <= budget; } catch { fits = false; }
    if (fits && !(count === 0 && choice.literals.length > 0 && pool.length > 0)) { economy.recordDelivery(rawTokens, economyTokens(text)); return text; }
    if (count === 0) break;
    count = Math.floor(count / 2);
  }
  if (choice.literals.length > 0) return (await economy.present(full, { ...choice, algorithm: 'targeted', literals: choice.literals.map(literal => JSON.stringify(literal).slice(1, -1)) }, 'mcp')).text;
  return (await economy.capture(full, { budget, transport: 'mcp' })).text;
}
