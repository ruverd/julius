import { test, expect } from 'bun:test';
import { optimize } from '../src/optimizer';

const content = Array(5).fill('neutral status line with enough characters to reduce and some additional ordinary status detail').join('\n');
const artifactId = '12345678-1234-1234-1234-123456789abc';
const context = { projectId: 'a', category: 'tool_output', content, recovery: { artifactId, available: true as const } };
const policy = { mode: 'safe' as const, version: '1.0.0', approved: true };

test('safe mode produces an offline candidate with labeled estimates', () => {
  const result = optimize(context, policy);
  expect(result.receipt.applied).toBe(true);
  expect(result.receipt.afterBytes).toBeLessThan(result.receipt.beforeBytes);
  expect(result.receipt.realizedSavings).toBeNull();
  expect(result.receipt.tokenEstimateMethod).toContain('heuristic');
  expect(result.receipt.evidence).toBe('heuristic_estimate');
  expect(result.receipt.tokenizer).toBeNull();
  expect(result.candidate).toContain(artifactId);
  expect(result.receipt.lineage.originalArtifactId).toBe(artifactId);
});

test('observe and protected data remain unchanged', () => {
  expect(optimize(context, { ...policy, mode: 'observe' }).candidate).toBe(content);
  expect(optimize({ ...context, protected: true }, policy).candidate).toBe(content);
  expect(optimize({ ...context, content: `ERROR\n${content}` }, policy).receipt.applied).toBe(false);
  expect(optimize({ ...context, content: `FAIL assertion\n${content}` }, policy).receipt.applied).toBe(false);
  expect(optimize({ ...context, content: `\0${content}` }, policy).receipt.applied).toBe(false);
});

test('policy and recompression fail closed', () => {
  expect(optimize(context, { ...policy, disabled: true }).receipt.reason).toBe('policy_disabled');
  expect(optimize(context, { ...policy, expiresAt: '2000-01-01T00:00:00Z' }).receipt.reason).toBe('policy_expired');
  expect(optimize(context, { ...policy, approved: false }).receipt.reason).toBe('approval_required');
  expect(optimize({ ...context, priorTransformId: 'prior' }, policy).receipt.reason).toBe('recompression_requires_opt_in');
  expect(optimize({ ...context, recovery: undefined }, policy).receipt.reason).toBe('recovery_required');
  expect(optimize({ ...context, recovery: { artifactId: 'bad', available: true } }, policy).receipt.applied).toBe(false);
});

test('invalid runtime input is rejected before optimization', () => {
  expect(() => optimize({ ...context, content: null as unknown as string }, policy)).toThrow(TypeError);
  expect(() => optimize({ ...context, content: 'x'.repeat(1024 * 1024 + 1) }, policy)).toThrow(RangeError);
});
