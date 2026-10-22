import { test } from 'node:test';
import assert from 'node:assert/strict';
import { decide, handoff, runIdeas } from '../scripts/experiments/ideas.js';

test('idea gates reject quality loss even when token savings look excellent', () => {
  assert.equal(decide(10000, 10, false), 'reject-quality-loss');
  assert.equal(decide(100, 100, true), 'reject-no-saving');
  assert.equal(decide(100, 120, true), 'reject-no-saving');
  assert.equal(decide(100, 50, true), 'advance-to-held-out-trial');
});
test('handoff prototype cannot use a delta after a context reset or mismatched base', () => {
  assert.equal(handoff('old', 'old new', '2', { epoch: '1', base: 'old' }).kind, 'full');
  assert.equal(handoff('old', 'old new', '1', { epoch: '1', base: 'other' }).kind, 'full');
  assert.equal(handoff('old', 'replacement', '1', { epoch: '1', base: 'old' }).kind, 'full');
});
test('offline probes preserve adverse findings, missing facts and unknown provider usage', async () => {
  const r = await runIdeas();
  assert.equal(r.providerUsage, null); assert.equal(r.codingTaskAccuracy, null);
  assert.equal(r.reuse.newCallerInvalidates, true);
  const selective = r.retrieval.find(x => x.fixture === 'middle-failure')!;
  assert.equal(selective.initialHasFact, false, 'Naive preview must fail the relevance check');
  assert.equal(selective.factsPreserved, true); assert.ok(selective.recoveryCalls > 0);
  const complete = r.retrieval.find(x => x.fixture === 'every-byte-required')!;
  assert.equal(complete.decision, 'reject-no-saving'); assert.ok(complete.candidateTokens > complete.baselineTokens);
  assert.equal(r.handoff.find(x => x.scenario === 'new-agent')!.mode, 'full');
});
