import { sources, envelope, decoded } from '../scripts/experiments/local-comparison.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { completeBody, deliveryArguments, comparisonDecision } from '../scripts/experiments/performance-comparison.mjs';
import { createHash } from 'node:crypto';

test('policy makes complete intent explicit and selects only a task-declared hint', () => {
  assert.deepEqual(deliveryArguments({ kind: 'complete' }, 'policy'), { delivery: 'complete' });
  assert.deepEqual(deliveryArguments({ kind: 'selective', recoveryHint: 'NEEDLE' }, 'policy'), { focus: 'NEEDLE' });
  assert.deepEqual(deliveryArguments({ kind: 'selective', recoveryHint: 'NEEDLE' }, 'compact-1200'), { budget: 1200 });
  assert.deepEqual(deliveryArguments({ kind: 'selective', recoveryHint: null }, 'policy'), {});
});

test('complete framing verifies original bytes and rejects corrupt or partial evidence', () => {
  const body = 'ação🙂\r\nneedle';
  const header = { delivery: 'complete', handle: 'sha256:' + createHash('sha256').update(body).digest('hex'), format: 'utf8', incomplete: false, totalBytes: Buffer.byteLength(body), omittedBytes: 0 };
  assert.equal(completeBody(JSON.stringify(header) + '\n' + body).toString(), body);
  assert.throws(() => completeBody(JSON.stringify(header) + '\n' + body + 'corrupt'), /integrity/);
  assert.throws(() => completeBody(JSON.stringify({ ...header, incomplete: true }) + '\n' + body), /incomplete/);
  assert.equal(completeBody('ordinary text'), null);
});

test('recovery parser preserves complete range framing and ordinary JSON envelopes', () => {
  const handle = 'sha256:' + 'a'.repeat(64);
  const range = { delivery: 'complete', handle, start: 5, end: 11, totalBytes: 11, format: 'utf8' };
  const result = envelope(JSON.stringify(range) + '\n' + 'ação');
  assert.equal(result.start, 5);
  assert.equal(decoded(result).toString(), 'ação');
  assert.equal(envelope(JSON.stringify({ ...range, content: 'ação' }, null, 2)).content, 'ação');
  assert.equal(envelope('ordinary text\nwith lines'), null);
});

test('comparison keeps quality failures, unknown counts and regressions', () => {
  assert.equal(comparisonDecision(100, 99, false), 'reject-quality');
  assert.equal(comparisonDecision(null, 99, true), 'inconclusive');
  assert.equal(comparisonDecision(100, 101, true), 'reject-no-saving');
  assert.equal(comparisonDecision(100, 99, true), 'advance-offline-only');
});

test('fixture generation honors the measured manifest', () => {
  const generated = sources('typescript', { functions: 2, callers: 1, target: 1 });
  assert.match(generated.files['catalog.ts'], /BENCH_MARKER_001: retry_limit=7/);
  assert.equal(generated.files['catalog.ts'].includes('BENCH_MARKER_002'), false);
  assert.equal(generated.files['callers.ts'].includes('caller001'), false);
});

test('plain Trail output is not parsed as an investigation envelope', async () => {
  const { structuredRecovery } = await import('../scripts/experiments/performance-contract.mjs');
  assert.equal(structuredRecovery('julius callers hello\ncaller001 core.ts'), null);
  assert.equal(structuredRecovery('{"evidence":[],"omittedEvidence":0}'), null);
  assert.equal(structuredRecovery('{"handle":"sha256:abc","omittedEvidence":1}'), null);
  const handle = 'sha256:' + 'a'.repeat(64);
  assert.equal(structuredRecovery(JSON.stringify({ handle, evidence: [], omittedEvidence: 2 })), handle);
});

test('targeted reruns reject unknown task IDs instead of silently omitting them', async () => {
  const { selectTasks } = await import('../scripts/experiments/performance-contract.mjs');
  const tasks = [{ kind: 'tiny' }, { kind: 'impact', id: 'investigation-impact' }];
  assert.deepEqual(selectTasks(tasks, ['investigation-impact']), [tasks[1]]);
  assert.deepEqual(selectTasks(tasks), tasks);
  assert.throws(() => selectTasks(tasks, ['missing']), /Unknown task/);
});
