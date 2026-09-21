import { expect, test } from 'bun:test';
import type { EconomyEvent } from '../src/events';
import { report, renderHtml, renderCsv } from '../src/reporting';

const window = { since: '2026-09-01T00:00:00.000Z', until: '2026-10-01T00:00:00.000Z', timezone: 'UTC' };
const base = { schemaVersion: 1 as const, occurredAt: '2026-09-21T00:00:00.000Z', sourceId: 'fixture', projectId: 'p', taskId: null, sessionId: 's', requestId: 'r', attemptId: 'a', clientId: 'sdk', adapterVersion: '1', modelId: 'model', providerId: null, executionLocation: 'unknown' as const, evidence: 'tokenizer_counted' as const };
function transform(id: string, before: number, after: number, sent = true): EconomyEvent {
  return { ...base, eventId: id, sourceEventId: id, eventType: 'transform', payload: { scope: 'request', inputTokens: before, outputTokens: after, tokenizer: 'fixture-tokenizer', transformId: id, parentTransformId: null, inputArtifactId: null, outputArtifactId: null, strategy: 'fixture', sent } };
}
test('ordered marginal reductions sum to 7000 and previews never count', () => {
  const data = report([transform('a', 10000, 4000), transform('b', 4000, 3000), transform('preview', 3000, 1, false)], window);
  expect(data.directInputReduction[0]?.tokens.total).toBe(7000);
  expect(data.candidateTransformsNotCounted).toBe(1);
});
test('negative reduction stays signed; no financial baseline invented', () => {
  const data = report([transform('increase', 10, 30)], window);
  expect(data.directInputReduction[0]?.tokens.total).toBe(-20);
  expect(data.financialSavingsUsd).toBeNull();
  expect(data.modeledCostUsd.total).toBeNull();
});
test('coverage never joins identical request IDs across projects', () => {
  const usage: EconomyEvent = { ...base, projectId: 'other', eventId: 'usage', sourceEventId: 'usage', eventType: 'usage', payload: { inputTokens: 20, outputTokens: 1, cacheReadTokens: null, cacheWriteTokens: null, complete: true, category: 'primary', callId: null, costUsd: null } };
  expect(report([usage, transform('a', 100, 20)], window).coverage.transformedObservedRequests).toBe(0);
});
test('unknown model and incomplete streams remain visible, exports escape injection', () => {
  const event: EconomyEvent = { ...base, evidence: 'provider_reported', modelId: null, clientId: '<script>alert(1)</script>', eventId: 'u', sourceEventId: 'u', eventType: 'usage', payload: { inputTokens: null, outputTokens: null, cacheReadTokens: null, cacheWriteTokens: null, complete: false, category: 'primary', callId: null, costUsd: null } };
  const data = report([event], window, 'client');
  expect(data.incompleteCalls).toBe(1);
  expect(data.unknownModels).toBe(1);
  expect(data.groups[0]?.input.total).toBeNull();
  expect(renderHtml(data)).not.toContain('<script>');
  event.clientId = '=HYPERLINK("evil")';
  expect(renderCsv(report([event], window, 'client'))).toContain("'=HYPERLINK");
});
