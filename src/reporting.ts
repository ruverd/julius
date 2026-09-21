import type { EconomyEvent } from './events';
import type { QueryWindow } from './query';

type NullableTotal = { known: number; unknownRecords: number; total: number | null };
function sum(values: (number | null)[]): NullableTotal {
  const known = values.reduce<number>((total, value) => total + (value ?? 0), 0);
  const unknownRecords = values.filter(value => value === null).length;
  return { known, unknownRecords, total: unknownRecords > 0 || values.length === 0 ? null : known };
}

export function report(events: EconomyEvent[], window: QueryWindow, by: 'model' | 'category' | 'client' = 'model') {
  const usage = events.filter(event => event.eventType === 'usage');
  const transforms = events.filter((event): event is Extract<EconomyEvent, {eventType: 'transform'}> => event.eventType === 'transform' && event.payload.sent);
  const groups = new Map<string, typeof usage>();
  for (const event of usage) {
    const key = by === 'model' ? event.modelId ?? 'unknown' : by === 'client' ? event.clientId : event.payload.category;
    groups.set(key, [...(groups.get(key) ?? []), event]);
  }
  const reductions = new Map<string, { scope: string; evidence: string; tokenizer: string | null; values: (number | null)[] }>();
  for (const event of transforms) {
    const p = event.payload;
    const key = JSON.stringify([p.scope, event.evidence, p.tokenizer, event.modelId]);
    const group = reductions.get(key) ?? { scope: p.scope, evidence: event.evidence, tokenizer: p.tokenizer, modelId: event.modelId, values: [] as (number | null)[] };
    group.values.push(p.inputTokens === null || p.outputTokens === null ? null : p.inputTokens - p.outputTokens);
    reductions.set(key, group);
  }
  const requestKey = (event: EconomyEvent) => event.requestId === null ? null : JSON.stringify([event.projectId, event.sessionId, event.requestId, event.attemptId]);
  const observedRequests = new Set(usage.map(requestKey).filter(key => key !== null));
  const transformedRequests = new Set(transforms.map(requestKey).filter(key => key !== null && observedRequests.has(key)));
  const modeledCosts = usage.map(event => event.modelId === null ? null : event.payload.costUsd);
  return {
    schemaVersion: 1,
    period: { ...window, interval: '[since, until)' },
    sources: [...new Set(events.map(event => event.sourceId))],
    observedCalls: usage.filter(event => event.payload.observationScope !== 'session_delta').length,
    sessionUsageDeltas: usage.filter(event => event.payload.observationScope === 'session_delta').length,
    incompleteCalls: usage.filter(event => !event.payload.complete).length,
    unknownModels: usage.filter(event => event.modelId === null).length,
    coverage: { transformedObservedRequests: transformedRequests.size, observedRequestsWithId: observedRequests.size, scope: 'Imported or instrumented requests only; unobserved traffic is unknown.' },
    directInputReduction: [...reductions.values()].map(({ values, ...rest }) => ({ ...rest, tokens: sum(values) })),
    candidateTransformsNotCounted: events.filter(event => event.eventType === 'transform' && !event.payload.sent).length,
    modeledCostUsd: sum(modeledCosts),
    auxiliaryCostUsd: sum(usage.filter(event => event.payload.category !== 'primary').map(event => event.modelId === null ? null : event.payload.costUsd)),
    financialSavingsUsd: null,
    baseline: 'Unavailable: no comparable financial baseline was recorded.',
    taskMeasurement: 'Incomplete: instrumentation does not establish that every call of a task was captured.',
    groups: [...groups.entries()].map(([key, items]) => ({
      key, calls: items.length,
      input: sum(items.map(event => event.payload.inputTokens)),
      output: sum(items.map(event => event.payload.outputTokens)),
      cacheRead: sum(items.map(event => event.payload.cacheReadTokens)),
      cacheWrite: sum(items.map(event => event.payload.cacheWriteTokens)),
      costUsd: sum(items.map(event => event.modelId === null ? null : event.payload.costUsd)),
      evidence: [...new Set(items.map(event => event.evidence))],
      locations: [...new Set(items.map(event => event.executionLocation))],
    })),
  };
}

export type Report = ReturnType<typeof report>;
const display = (value: number | null): string => value === null ? 'unavailable' : String(value);
export function renderText(data: Report): string {
  return [
    'Julius — evidence-aware report',
    `Period: ${data.period.since} ≤ time < ${data.period.until} (${data.period.timezone})`,
    `Sources: ${data.sources.join(', ') || 'none'}`,
    `Observed calls: ${data.observedCalls}; incomplete: ${data.incompleteCalls}; unknown model: ${data.unknownModels}`,
    `Session usage deltas: ${data.sessionUsageDeltas} (not a known call count)`,
    `Coverage: ${data.coverage.transformedObservedRequests}/${data.coverage.observedRequestsWithId} observed requests with IDs transformed`,
    ...data.directInputReduction.map(item => `Direct input reduction: ${display(item.tokens.total)} tokens; known subtotal ${item.tokens.known}; ${item.scope}; ${item.evidence}; tokenizer ${item.tokenizer ?? 'unknown'}`),
    ...(data.directInputReduction.length ? [] : ['Direct input reduction: unavailable (no sent transformation evidence)']),
    `Modeled cost USD: ${display(data.modeledCostUsd.total)}; known subtotal: ${data.modeledCostUsd.known}`,
    `Observed auxiliary modeled cost USD: ${display(data.auxiliaryCostUsd.total)}`,
    `Estimated financial savings USD: unavailable. ${data.baseline}`,
    `Task measurement: ${data.taskMeasurement}`,
    ...data.groups.map(group => `${group.key}: calls=${group.calls}, input=${display(group.input.total)}, output=${display(group.output.total)}, evidence=${group.evidence.join(',')}`),
  ].join('\n');
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]!));
}
export function renderHtml(data: Report): string {
  return `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>Julius evidence report</title><style>:root{color-scheme:light dark}body{font:16px system-ui;max-width:1000px;margin:3rem auto;padding:1rem}pre{white-space:pre-wrap;line-height:1.7}table{border-collapse:collapse;width:100%}td,th{padding:.7rem;text-align:left;border-bottom:1px solid #888}caption{text-align:left;font-weight:bold}</style><main><h1>Julius</h1><p>Local evidence report. No model calls. No external resources.</p><pre>${escapeHtml(renderText(data))}</pre><table><caption>Observed usage by model or selected dimension</caption><thead><tr><th scope="col">Group</th><th scope="col">Calls</th><th scope="col">Input</th><th scope="col">Output</th><th scope="col">Evidence</th></tr></thead><tbody>${data.groups.map(group => `<tr><th scope="row">${escapeHtml(group.key)}</th><td>${group.calls}</td><td>${display(group.input.total)}</td><td>${display(group.output.total)}</td><td>${escapeHtml(group.evidence.join(', '))}</td></tr>`).join('')}</tbody></table></main></html>`;
}

export function renderCsv(data: Report): string {
  const cell = (value: unknown) => `"${String(value ?? 'unavailable').replace(/^[=+@\-\t\r]/, "'$&").replaceAll('"', '""')}"`;
  return [['group', 'calls', 'input_tokens', 'output_tokens', 'modeled_cost_usd', 'evidence'], ...data.groups.map(group => [group.key, group.calls, group.input.total, group.output.total, group.costUsd.total, group.evidence.join(';')])].map(row => row.map(cell).join(',')).join('\n');
}
