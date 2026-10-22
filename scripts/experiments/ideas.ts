/** Offline falsification probes. Prototype policies stay outside product code. */
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Economy, economyTokens } from '../../src/economy/index.js';
import { runInvestigation } from '../../src/investigation/index.js';
import { callCompact } from '../../src/mcp/compact.js';
import { fileURLToPath } from 'node:url';

const wire = (value: unknown) => economyTokens(JSON.stringify(value) + '\n');
function exchange(operation: string, args: object, text: string, budget = 400) {
  return wire({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'julius_call', arguments: { operation, args, budget } } }) +
    wire({ jsonrpc: '2.0', id: 1, result: { content: [{ type: 'text', text }], isError: false } });
}
function schemaExchange(operation: string, text: string) {
  return wire({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'julius_discover', arguments: { operation } } }) +
    wire({ jsonrpc: '2.0', id: 1, result: { content: [{ type: 'text', text }], isError: false } });
}
export function decide(baseline: number, candidate: number, factsPreserved: boolean) {
  return !factsPreserved ? 'reject-quality-loss' : candidate >= baseline ? 'reject-no-saving' : 'advance-to-held-out-trial';
}

async function composition(root: string) {
  writeFileSync(join(root, 'math.ts'), 'export function add(x: number) { return x + 1; }\n');
  writeFileSync(join(root, 'consumer.ts'), 'import { add } from "./math";\nexport function total() { return add(2); }\n');
  const args = { recipe: 'change-impact' as const, paths: ['math.ts'], depth: 2 };
  const cold = await runInvestigation(root, args);
  const warm = await runInvestigation(root, args);
  assert.equal(warm.reused, true);
  assert.deepEqual(warm.evidence, cold.evidence);
  assert.ok(cold.evidence.some(e => e.id === 'consumer.ts#total' && e.role === 'dependent'));
  const separate = [
    ['julius_file_api', { file: 'math.ts' }],
    ['julius_trace_calls', { symbol: 'math.ts', depth: 2 }],
  ] as const;
  let baseline = 0; let observed = '';
  for (const [operation, input] of separate) {
    const schema = await callCompact(root, 'julius_discover', { operation });
    baseline += schemaExchange(operation, schema.text);
    const result = await callCompact(root, 'julius_call', { operation, args: input, budget: 16000 });
    assert.equal(result.isError, false, result.text); observed += result.text;
    baseline += exchange(operation, input, result.text, 16000);
  }
  assert.match(observed, /total/); assert.match(observed, /consumer.ts/);
  const schema = await callCompact(root, 'julius_discover', { operation: 'investigation.execute' });
  const candidateReply = await callCompact(root, 'julius_call', { operation: 'investigation.execute', args, budget: 16000 });
  assert.equal(candidateReply.isError, false, candidateReply.text);
  assert.ok(JSON.parse(candidateReply.text).evidence.some((e: { id: string }) => e.id === 'consumer.ts#total'));
  const candidate = schemaExchange('investigation.execute', schema.text) + exchange('investigation.execute', args, candidateReply.text, 16000);
  writeFileSync(join(root, 'new.ts'), 'import { add } from "./math";\nexport function newCaller() { return add(4); }\n');
  const changed = await runInvestigation(root, args);
  assert.equal(changed.reused, false);
  assert.ok(changed.evidence.some(e => e.id === 'new.ts#newCaller'));
  return {
    composition: { fixture: 'tiny-impact', baselineTokens: baseline, candidateTokens: candidate,
      factsPreserved: true, decision: decide(baseline, candidate, true),
      limitation: 'Common compact interface initialization cancels. Schemas and request/result envelopes counted. Hand-authored calls; model planning and repeated prompt processing are unknown. Not upstream Trail.' },
    reuse: { evidenceUnchanged: true, newCallerInvalidates: true,
      coldDeliveryTokens: economyTokens(JSON.stringify(cold)), warmDeliveryTokens: economyTokens(JSON.stringify(warm)),
      decision: 'computation-reuse-only', limitation: 'A cache hit still delivers all evidence. Do not claim avoided prompt tokens or speedup from this probe.' },
  };
}

async function retrieval(root: string, full: boolean) {
  const economy = new Economy(root);
  const text = Array.from({ length: 200 }, (_, i) => `PASS unrelated case ${i}: expected result matched`).join('\n') + '\nFAIL checkout: expected 403 received 200\n' + 'PASS trailing case\n'.repeat(100);
  const baseline = exchange('fixture.output', {}, text);
  const result = await economy.capture(text, { budget: 400, transport: 'mcp' });
  assert.ok(result.handle);
  let cost = exchange('fixture.output', {}, result.text);
  const initialHasFact = result.text.includes('FAIL checkout: expected 403 received 200');
  let recovered: string;
  let reads = 0;
  if (full) {
    let start = 0; const bytes: Buffer[] = [];
    while (start < Buffer.byteLength(text)) {
      const args = { handle: result.handle!, start };
      const read = await economy.read(result.handle!, { start, budget: 400, transport: 'mcp' });
      assert.ok(read.bytes.length > 0); bytes.push(read.bytes); start += read.bytes.length; reads++;
      cost += exchange('context.read', args, read.text);
      assert.ok(reads < 200, 'Recovery must terminate');
    }
    recovered = Buffer.concat(bytes).toString(); assert.equal(recovered, text);
  } else {
    // The query hint is declared from the task, never extracted from a preview.
    const args = { handle: result.handle!, search: 'FAIL checkout' };
    const read = await economy.read(result.handle!, { search: args.search, budget: 400, transport: 'mcp' });
    cost += exchange('context.read', args, read.text); reads++; recovered = read.text;
    assert.ok(recovered.includes('FAIL checkout: expected 403 received 200'));
  }
  return { fixture: full ? 'every-byte-required' : 'middle-failure', baselineTokens: baseline, candidateTokens: cost,
    initialHasFact, recoveryCalls: reads, factsPreserved: true, decision: decide(baseline, cost, true),
    limitation: 'Frozen output replay, no model. Includes result/recovery envelopes; excludes common interface and discovery. The budget cap itself is not a relevance guarantee.' };
}

/** Test-only protocol model: a hash alone is insufficient for a fresh receiver. */
export function handoff(base: string, next: string, senderEpoch: string, receiver?: { epoch: string; base: string }) {
  return receiver?.epoch === senderEpoch && receiver.base === base && next.startsWith(base)
    ? { kind: 'append' as const, text: next.slice(base.length) }
    : { kind: 'full' as const, text: next };
}
function handoffProbe() {
  const base = 'verified finding\n'.repeat(100); const next = base + 'new finding\n';
  const scenarios = [
    { name: 'same-context', receiver: { epoch: '1', base } },
    { name: 'new-agent', receiver: undefined },
    { name: 'compacted', receiver: { epoch: '2', base } },
    { name: 'wrong-base', receiver: { epoch: '1', base: 'different' } },
  ];
  return scenarios.map(({ name, receiver }) => {
    const result = handoff(base, next, '1', receiver);
    const restored = result.kind === 'append' ? receiver!.base + result.text : result.text;
    assert.equal(restored, next);
    return { scenario: name, mode: result.kind, factsPreserved: true,
      decision: result.kind === 'append' ? 'requires-host-context-contract' : 'must-send-self-contained-evidence' };
  });
}

export async function runIdeas() {
  const root = mkdtempSync(join(tmpdir(), 'julius-idea-probes-'));
  try {
    const experiments = await composition(root);
    return { version: 1, encoding: 'cl100k_base', providerUsage: null, providerCost: null, codingTaskAccuracy: null,
      scope: 'Offline falsification probes. Passing means worth a held-out experiment, never production approval or provider savings.',
      ...experiments, retrieval: [await retrieval(root, false), await retrieval(root, true)], handoff: handoffProbe(),
      nextGate: 'Expand only a promising mechanism to unseen tasks; require independent correctness and complete provider usage before enabling or claiming savings.' };
  } finally { rmSync(root, { recursive: true, force: true }); }
}
if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  console.log(JSON.stringify(await runIdeas(), null, 2));
}
