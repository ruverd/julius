import { Julius } from '../src/sdk';
import type { EconomyEvent } from '../src/events';

// Synthetic fixtures, not provider measurements or benchmark results.
const julius = new Julius(process.env.JULIUS_HOME ?? '.julius-demo');
try {
  const common = { schemaVersion: 1 as const, occurredAt: '2026-09-21T12:00:00.000Z', sourceId: 'synthetic-demo', projectId: 'demo', taskId: 'DEMO-1', sessionId: 'demo-session', requestId: 'demo-request', attemptId: 'demo-attempt', clientId: 'fixture', adapterVersion: '1.0.0', modelId: 'synthetic-model', providerId: null, executionLocation: 'unknown' as const, evidence: 'heuristic_estimate' as const };
  const stages = [[10000, 4000], [4000, 3000]] as const;
  for (const [index, [inputTokens, outputTokens]] of stages.entries()) {
    const id = `demo-transform-${index}`;
    const event: EconomyEvent = { ...common, eventId: id, sourceEventId: id, eventType: 'transform', payload: { scope: 'request', inputTokens, outputTokens, tokenizer: null, transformId: id, parentTransformId: index ? 'demo-transform-0' : null, inputArtifactId: `demo-artifact-${index}`, outputArtifactId: `demo-artifact-${index + 1}`, strategy: 'synthetic-example', sent: true } };
    julius.ledger.record(event);
  }
  julius.recordUsage({ ...common, eventId: 'demo-usage', sourceEventId: 'demo-usage', eventType: 'usage', payload: { inputTokens: 3000, outputTokens: 100, cacheReadTokens: null, cacheWriteTokens: null, complete: true, category: 'primary', callId: 'demo-call', costUsd: null } });
  console.log(JSON.stringify(julius.report({ since: '2026-09-21T00:00:00Z', until: '2026-09-22T00:00:00Z' }), null, 2));
} finally { julius.close(); }
