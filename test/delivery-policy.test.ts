import { test } from 'node:test';
import assert from 'node:assert/strict';
import { decideDelivery, runDeliveryPolicy } from '../scripts/experiments/delivery-policy.js';

test('delivery gate rejects quality loss, unknown tokens, and equal or higher cost', () => {
  const fixed = { oneFact: 100, complete: 100, mixed: 100 };
  assert.equal(decideDelivery({ quality: false, policy: fixed, fixed }), 'reject-quality');
  assert.equal(decideDelivery({ quality: true, policy: { oneFact: null, complete: 1, mixed: 1 }, fixed }), 'inconclusive');
  assert.equal(decideDelivery({ quality: true, policy: fixed, fixed }), 'reject-no-saving');
  assert.equal(decideDelivery({ quality: true, policy: { oneFact: 99, complete: 99, mixed: 99 }, fixed }), 'advance-offline-only');
});

test('offline probe preserves the adverse full-content case and beats fixed preview', async () => {
  const report = await runDeliveryPolicy();
  assert.equal(report.providerUsage, null);
  assert.equal(report.codingTaskAccuracy, null);
  assert.equal(report.decision, 'advance-offline-only');
  assert.ok(report.savings.withoutFlagVersusRaw < 0);
  assert.ok(report.savings.oneFact > 0);
  assert.ok(report.savings.complete > 0);
  assert.ok(report.savings.mixed > 0);
});
