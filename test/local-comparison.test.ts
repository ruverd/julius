import { test } from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error Experiment-only JavaScript module, outside the product build.
import { decision, decoded, envelope, expectedFacts } from '../scripts/experiments/local-comparison.mjs';

test('comparison never promotes quality loss, unknown usage or negative savings', () => {
  assert.equal(decision(1000, 10, false), 'reject-quality');
  assert.equal(decision(null, 10, true), 'inconclusive');
  assert.equal(decision(100, null, true), 'inconclusive');
  assert.equal(decision(100, 101, true), 'reject-no-saving');
  assert.equal(decision(100, 100, true), 'reject-no-saving');
  assert.equal(decision(100, 99, true), 'advance-offline-only');
});

test('recovery recognizes byte envelopes without treating arbitrary JSON as a handle', () => {
  assert.equal(envelope('{"recipe":"change-impact","evidence":[]}'), null);
  assert.equal(envelope('ordinary output'), null);
  const source = Buffer.from('ação🙂\r\n');
  const first = { handle: `sha256:${'a'.repeat(64)}`, start: 0, end: 3, content: source.subarray(0, 3).toString('base64'), format: 'base64' };
  const last = { content: source.subarray(3).toString('base64'), format: 'base64' };
  assert.deepEqual(Buffer.concat([decoded(envelope(JSON.stringify(first))), decoded(last)]), source);
});

test('independent oracle requires every marker and caller, including omitted middle evidence', () => {
  const facts = expectedFacts({ kind: 'complete' }, { functions: 3, target: 1 });
  assert.deepEqual(facts, ['BENCH_MARKER_000: retry_limit=3', 'BENCH_MARKER_001: retry_limit=7', 'BENCH_MARKER_002: retry_limit=3']);
  assert.deepEqual(expectedFacts({ kind: 'impact', expectedCallers: 2 }), ['hello', 'caller000', 'caller001']);
  assert.equal(facts.every((fact: string) => `${facts[0]}\n${facts[2]}`.includes(fact)), false);
});
