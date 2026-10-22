/**
 * Tests for the shared "tokens saved" estimate ({@link savingsFor} +
 * {@link withSavings}) that every retrieval-style command routes through.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { savingsFor, savingsLine, withSavings, toTokens, setInputRate } from '../src/context/savings.js';
import type { GraphV1, NodeV1 } from '../src/graph/types.js';

function fileNode(path: string, chars?: number): NodeV1 {
  return {
    id: path,
    name: path,
    kind: 'file',
    path,
    span: 'L1-L1',
    signature: null,
    exported: true,
    origin: 'ast',
    body_hash: '',
    summary_state: 'pending',
    summary: null,
    crux: null,
    chars,
  };
}

function graphOf(nodes: NodeV1[]): GraphV1 {
  return { meta: { version: 1, nodeCount: nodes.length, edgeCount: 0, languages: [] }, nodes, edges: [] };
}

test('savingsFor: sums the sizes of the distinct baseline files', () => {
  const g = graphOf([fileNode('a.ts', 400), fileNode('b.ts', 600)]);
  const s = savingsFor(g, ['a.ts', 'b.ts', 'a.ts']); // duplicate a.ts counted once
  assert.deepEqual(s, { files: 2, baselineChars: 1000 });
});

test('savingsFor: skips files with no known size, returns undefined when none are sized', () => {
  const g = graphOf([fileNode('a.ts'), fileNode('b.ts', 800)]);
  assert.deepEqual(savingsFor(g, ['a.ts', 'b.ts']), { files: 1, baselineChars: 800 });
  assert.equal(savingsFor(graphOf([fileNode('a.ts')]), ['a.ts']), undefined);
  assert.equal(savingsFor(g, ['missing.ts']), undefined);
});

test('savingsLine reports a labelled counterfactual and preserves losses', () => {
  const line = savingsLine('x'.repeat(40), { files: 2, baselineChars: 8000 });
  assert.match(line, /counterfactual full-file-read difference ≈ 1990/);
  assert.match(line, /chars\/4 estimate/);
  assert.doesNotMatch(line, /tell the user|tokens saved|\$/);
  assert.equal(savingsLine('anything', undefined), '');
  assert.match(savingsLine('x'.repeat(1000), { files: 1, baselineChars: 40 }), /≈ -240/);
});

test('withSavings keeps the original body and one estimate', () => {
  const body = 'line1\nline2\nline3';
  const out = withSavings(body, { files: 2, baselineChars: 8000 });
  assert.match(out.split('\n')[0], /counterfactual/);
  assert.ok(out.endsWith(body));
  assert.equal(withSavings('body', undefined), 'body');
});

test('input billing rates cannot price hypothetical graph differences', () => {
  for (const rate of [null, 5, NaN, Infinity, 0, -1]) {
    setInputRate(rate);
    assert.doesNotMatch(savingsLine('body', { files: 1, baselineChars: 8000 }), /\$|this turn/);
  }
});
