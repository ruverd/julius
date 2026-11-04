import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, writeFileSync, rmSync } from 'node:fs';
import { join, relative } from 'node:path';
import { pathToFileURL } from 'node:url';
import { extractionCases, queryCases } from './cases.mjs';

const [product, corpus, mode, output, corpusId] = process.argv.slice(2);
const { counters, resetCounters } = product.endsWith('/candidate') ? await import('./adapter.mjs') : {
  counters: { files: 0, nativeMs: 0, materializeMs: 0, bytes: 0 }, resetCounters() {},
};
const load = name => import(pathToFileURL(join(product, 'dist', name)));
export function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value !== null && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
  return value;
}
const hash = value => createHash('sha256').update(JSON.stringify(canonical(value))).digest('hex');
const emit = value => console.log(JSON.stringify(value));
const resource = () => ({ maxRSSKiB: process.resourceUsage().maxRSS, memory: process.memoryUsage() });
if (mode === 'extract') {
  const { extractFile, languageOf } = await load('graph/extract.js');
  const cases = [...extractionCases];
  function visit(dir) { for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) visit(path);
    else if (['typescript', 'tsx'].includes(languageOf(path))) cases.push([relative(corpus, path), readFileSync(path, 'utf8')]);
  } }
  visit(corpus);
  const results = [];
  resetCounters(); const started = performance.now();
  for (const [path, source] of cases) results.push({ path, result: extractFile(path, source, languageOf(path)) });
  const elapsedMs = performance.now() - started;
  const resources = resource();
  writeFileSync(output, JSON.stringify(results));
  emit({ cases: cases.length, elapsedMs, ...resources, counters, hashes: results.map(row => hash(row)) });
} else if (mode === 'build') {
  const { buildGraph } = await load('graph/build.js');
  const probe = join(corpus, 'native_probe.ts'); const added = join(corpus, 'native_added.ts');
  const original = 'export function nativeProbe() { return "native_probe_original"; }\n';
  if (output === 'full') { writeFileSync(probe, original); rmSync(added, { force: true }); }
  const rows = [];
  for (const phase of [output]) {
    if (phase === 'one-file-edit') writeFileSync(probe, original.replace('native_probe_original', 'native_probe_edited'));
    if (phase === 'addition') writeFileSync(added, 'import { nativeProbe } from "./native_probe"; export function addedProbe() { return nativeProbe(); }\n');
    if (phase === 'deletion') rmSync(added);
    resetCounters();
    const started = performance.now();
    const result = await buildGraph(corpus, { ...(phase === 'full' ? { reuse: false } : {}) });
    const elapsedMs = performance.now() - started;
    const resources = resource();
    assert.deepEqual(result.errors, []);
    assert.equal(result.nativeFallback, undefined, 'Compare native parsing with native parsing');
    const graph = JSON.parse(readFileSync(result.graphPath));
    const lexical = JSON.parse(readFileSync(join(result.contextDir, '.cache/ask-index.json')));
    rows.push({ phase, elapsedMs, ...resources, counters: { ...counters }, parsed: result.parsed, reused: result.reused,
      nodes: graph.nodes.length, edges: graph.edges.length, graphHash: hash(graph), lexicalHash: hash(lexical) });
  }
  emit({ rows });
} else if (mode === 'query') {
  const { ask } = await load('ask/ask.js');
  const cases = queryCases(corpusId);
  const parity = cases.map(c => ({ id: c.id, hash: hash(ask(corpus, c.query, c.options)) }));
  const timing = cases.filter(c => c.id.endsWith('/default')).slice(0, 5);
  for (let i = 0; i < 3; i++) for (const c of timing) ask(corpus, c.query, c.options);
  global.gc?.();
  const rows = [];
  for (let pass = 0; pass < 10; pass++) for (const c of timing) {
    const start = performance.now(); const result = ask(corpus, c.query, c.options);
    const elapsedMs = performance.now() - start;
    rows.push({ id: c.id, pass, elapsedMs, hash: hash(result) });
  }
  emit({ parity, rows, ...resource() });
} else { throw new Error(`Unknown mode ${mode}`); }
