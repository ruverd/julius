import { test } from 'node:test';
import assert from 'node:assert/strict';
import { compareTrials, type Trial } from '../src/evaluation/index.js';
const record = (arm: Trial['arm'], extra: Partial<Trial> = {}): Trial => ({ task: 'impact', taskRevision: 'fixture-v1', repetition: 0, arm, revision: `${arm}-v1`, host: 'test-host', model: 'test-model', outcome: 'pass', usage: { inputTokens: 100, cachedInputTokens: 50, outputTokens: 20, costUsd: 0.1 }, ...extra });
test('provider trial totals include failed work and do not double-count cached input', () => {
  const r = compareTrials([record('trail'), record('julius', { outcome: 'fail', usage: { inputTokens: 200, cachedInputTokens: 150, outputTokens: 40, costUsd: 0.2 } })]);
  assert.equal(r.trail.totalTokens, 120); assert.equal(r.julius.totalTokens, 240);
  assert.equal(r.tokenReduction, -1); assert.equal(r.julius.costPerSuccessUsd, null); assert.equal(r.successDifference, -1);
});
test('unknown usage propagates instead of becoming savings', () => {
  const r = compareTrials([record('trail'), record('julius', { usage: { inputTokens: null, cachedInputTokens: null, outputTokens: 10, costUsd: null } })]);
  assert.equal(r.tokenReduction, null); assert.equal(r.costReduction, null); assert.equal(r.julius.usageCoverage.tokens, 0);
});
test('unmatched, duplicate and incompatible trials are rejected', () => {
  assert.throws(() => compareTrials([record('trail')]), /Matched/);
  assert.throws(() => compareTrials([record('trail'), record('julius', { model: 'other' })]), /same task/);
  assert.throws(() => compareTrials([record('trail'), record('trail')]), /Duplicate/);
  assert.throws(() => compareTrials([record('trail'), record('julius', { usage: { inputTokens: 1, cachedInputTokens: 2, outputTokens: 0, costUsd: 0 } })]), /subset/);
});
