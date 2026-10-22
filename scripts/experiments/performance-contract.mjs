import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';

export function deliveryArguments(task, arm) {
  if (!arm.startsWith('policy')) return { budget: 1200 };
  if (task.kind === 'complete') return { delivery: 'complete' };
  const focus = task.initialFocus ?? task.recoveryHint;
  return task.kind === 'selective' && focus ? { focus } : {};
}

export function completeBody(text) {
  const split = text.indexOf('\n');
  if (split < 0) return null;
  let header;
  try { header = JSON.parse(text.slice(0, split)); } catch { return null; }
  if (header.delivery !== 'complete') return null;
  assert.equal(header.incomplete, false, 'Complete evidence is incomplete');
  const bytes = Buffer.from(text.slice(split + 1), header.format === 'base64' ? 'base64' : 'utf8');
  assert.equal(bytes.length, header.totalBytes, 'Complete byte integrity');
  assert.equal(createHash('sha256').update(bytes).digest('hex'), String(header.handle).slice(7), 'Complete digest integrity');
  return bytes;
}

export function comparisonDecision(baseline, candidate, quality) {
  if (!quality) return 'reject-quality';
  if (baseline === null || candidate === null) return 'inconclusive';
  return candidate < baseline ? 'advance-offline-only' : 'reject-no-saving';
}

export function structuredRecovery(text) {
  let parsed;
  try { parsed = JSON.parse(text); } catch { return null; }
  return parsed && Array.isArray(parsed.evidence) && parsed.omittedEvidence > 0 && /^sha256:[a-f0-9]{64}$/.test(parsed.handle) ? parsed.handle : null;
}

export function selectTasks(tasks, ids) {
  if (!ids) return tasks;
  for (const id of ids) assert.ok(tasks.some(task => (task.id ?? task.kind) === id), `Unknown task: ${id}`);
  return tasks.filter(task => ids.includes(task.id ?? task.kind));
}
