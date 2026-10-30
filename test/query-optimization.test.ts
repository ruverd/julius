import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, readFileSync, rmSync, statSync, utimesSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { buildGraph } from '../src/graph/build.js';
import { ask, formatAsk, skeleton, type AskResult } from '../src/ask/ask.js';
import { personalizedPageRankPrepared, preparePageRankTopology } from '../src/ask/graphrank.js';
import { loadGraphCached, loadAskIndexCached } from '../src/graph/load.js';
import { writeGraph, wiringPath } from '../src/graph/write.js';
import { writeAskIndex, askIndexPath } from '../src/ask/index-file.js';
import type { GraphV1, NodeV1 } from '../src/graph/types.js';
// @ts-expect-error Frozen JavaScript reference is test-only.
import { referencePageRank } from './fixtures/pagerank-reference.mjs';

test('dense PageRank exactly preserves reference scores and encounter order across graph shapes and options', () => {
  let state = 0x5eeda11;
  const random = () => { state = (Math.imul(state, 1664525) + 1013904223) >>> 0; return state / 2 ** 32; };
  for (let trial = 0; trial < 300; trial++) {
    const count = trial % 2 ? 1 + Math.floor(random() * 55) : 257 + Math.floor(random() * 300);
    const nodes = Array.from({ length: count }, (_, i) => ({ id: `n${i}` } as NodeV1));
    const edges = Array.from({ length: Math.floor(random() * count * 5) }, () => ({
      source: `n${Math.floor(random() * (count + 2))}`, target: `n${Math.floor(random() * (count + 2))}`,
      relation: random() > 0.3 ? 'calls' : 'imports', confidence: 'extracted',
    })) as GraphV1['edges'];
    const graph = { nodes, edges } as GraphV1;
    const topology = preparePageRankTopology(graph, trial % 3 === 0 ? id => Number(id.slice(1)) % 2 === 0 : undefined);
    const order = [...nodes].sort(() => random() - 0.5);
    const seeds = new Map(order.map(n => [n.id, random() > 0.2 ? random() * 10 : 0]));
    seeds.set('missing', 5);
    const options = { alpha: [0, 0.25, 0.6, 1][trial % 4], iters: [0, 1, 2, 25, 3.5][trial % 5] };
    const expected = referencePageRank(topology, seeds, options);
    assert.deepEqual([...personalizedPageRankPrepared(topology, seeds, options)], [...expected], `trial ${trial}`);
  }
  const topology = { ids: new Set(['seed']), adjacency: new Map([['seed', ['outside', 'outside']]]) };
  assert.deepEqual([...personalizedPageRankPrepared(topology, new Map([['seed', 1]]))], [...referencePageRank(topology, new Map([['seed', 1]]))]);
});

test('formatted evidence keeps each snippet once while retaining distinct descriptions and citations', () => {
  for (const mode of ['lexical', 'structural'] as const) {
    const result = { query: 'retry', mode, hits: [
      { kind: 'symbol', title: 'retry', pointer: 'client.ts:L1-L3', score: 1, relation: 'calls', snippet: 'return retry();', code: 'function retry() {\n  return retry();\n}' },
      { kind: 'symbol', title: 'backoff', pointer: 'client.ts:L4-L6', score: 0.5, relation: 'calls', snippet: 'Applies bounded exponential backoff.', code: 'function backoff() { return 1; }' },
    ] } as AskResult;
    const rendered = formatAsk(result);
    assert.equal(rendered.split('return retry();').length - 1, 1);
    assert.ok(rendered.includes('Applies bounded exponential backoff.'));
    for (const hit of result.hits) { assert.ok(rendered.includes(hit.pointer)); assert.ok(rendered.includes(hit.code!)); }
    const withoutCode = formatAsk({ ...result, hits: [{ ...result.hits[0], code: undefined }] });
    assert.ok(withoutCode.includes('return retry();'));
  }
});

test('edited learned code never returns a stale crux or summary as current query evidence', async () => {
  const root = mkdtempSync(join(tmpdir(), 'julius-stale-query-'));
  try {
    const source = join(root, 'math.ts');
    writeFileSync(source, 'export function calculate() { return 7; }\nexport function caller() { return calculate(); }\n');
    const first = await buildGraph(root, { graphOnly: true });
    const graph = JSON.parse(readFileSync(first.graphPath, 'utf8')) as GraphV1;
    const calculate = graph.nodes.find(n => n.name === 'calculate')!;
    calculate.summary = 'Returns the old value seven.'; calculate.summary_state = 'ready';
    calculate.crux = { code: 'return 7;', span: calculate.span };
    writeGraph(graph, first.contextDir);
    writeFileSync(source, 'export function calculate() { return 9; }\nexport function caller() { return calculate(); }\n');
    const changed = await buildGraph(root, { graphOnly: true });
    const stored = JSON.parse(readFileSync(changed.graphPath, 'utf8')) as GraphV1;
    assert.equal(stored.nodes.find(n => n.name === 'calculate')!.summary_state, 'stale');
    for (const query of ['calculate', 'what does caller call']) {
      const hit = ask(root, query, { source: true }).hits.find(h => h.title.startsWith('calculate'))!;
      assert.ok(hit, query);
      assert.match(hit.code!, /return 9/);
      assert.doesNotMatch(hit.code!, /return 7/);
      assert.doesNotMatch(hit.snippet, /old value seven/);
    }
    assert.equal(skeleton(root, 'math.ts').entries.find(e => e.name === 'calculate')!.summary, undefined);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('atomic replacement preserving file size and mtime invalidates graph and lexical caches', () => {
  const root = mkdtempSync(join(tmpdir(), 'julius-cache-identity-'));
  const graph = (name: string) => ({ nodes: [{ id: name, name, kind: 'function', path: 'a.ts', span: 'L1-L1', signature: null, summary: null }], edges: [] } as unknown as GraphV1);
  const timestamp = new Date('2026-01-01T00:00:00.000Z');
  try {
    writeGraph(graph('aa'), root); writeAskIndex(root, graph('aa'));
    for (const path of [wiringPath(root), askIndexPath(root)]) utimesSync(path, timestamp, timestamp);
    const oldGraph = loadGraphCached(root); const oldIndex = loadAskIndexCached(root);
    const size = statSync(wiringPath(root)).size;
    writeGraph(graph('bb'), root);
    writeAskIndex(root, graph('bb'));
    for (const path of [wiringPath(root), askIndexPath(root)]) utimesSync(path, timestamp, timestamp);
    assert.equal(statSync(wiringPath(root)).size, size);
    assert.notEqual(loadGraphCached(root), oldGraph);
    assert.equal(loadGraphCached(root)!.nodes[0].id, 'bb');
    assert.notEqual(loadAskIndexCached(root), oldIndex);
    assert.equal(loadAskIndexCached(root)!.docs[0].id, 'bb');
  } finally { rmSync(root, { recursive: true, force: true }); }
});
