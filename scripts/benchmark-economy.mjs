/** Offline transport experiment at the graph-result boundary, not agent accuracy. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Economy, economyTokens, ECONOMY_ENCODING } from '../dist/economy/index.js';
import { COMPACT_TOOLS, COMPACT_INSTRUCTIONS, callCompact } from '../dist/mcp/compact.js';
import { TOOLS } from '../dist/mcp/tools.js';
import { mcpInstructions } from '../dist/mcp/instructions.js';

const lines = (n, f) => Array.from({ length: n }, (_, i) => f(i)).join('\n') + '\n';
const fixtures = [
  { name: 'passing-tests', text: lines(800, i => `PASS test ${i}: expected response accepted`) + 'RESULT: 800 passed; 0 failed\n', facts: ['RESULT: 800 passed; 0 failed'], hint: 'RESULT:' },
  { name: 'middle-failure', text: lines(400, i => `PASS case ${i}`) + 'FAIL auth.test.ts:73 expected 403 received 200\n' + lines(400, i => `PASS remainder ${i}`), facts: ['FAIL auth.test.ts:73 expected 403 received 200'], hint: 'FAIL auth.test.ts'  },
  { name: 'long-line', text: 'prefix '.repeat(900) + 'RETRY_LIMIT=17 ' + 'suffix '.repeat(900), facts: ['RETRY_LIMIT=17'], hint: 'RETRY_LIMIT=' },
  { name: 'source-like', text: lines(250, i => `export function handler${i}(id: string) { return repository.load(id); }`) + 'export const MAX_RETRIES = 7;\n', facts: ['export const MAX_RETRIES = 7;'], hint: 'export const MAX_RETRIES' },
  { name: 'unicode', text: lines(500, i => `記録 ${i}: café 🌱 accepted`) + '終点: 東京 ✅\r\n', facts: ['終点: 東京 ✅'], hint: '終点:' },
  { name: 'small', text: 'OK: 3 passed\n', facts: ['OK: 3 passed'] },
  { name: 'high-entropy', text: lines(500, i => `record ${i}: ${createHash('sha256').update(`fixed-seed-${i}`).digest('hex')}`) + 'CHECKSUM_VALID=true\n', facts: ['CHECKSUM_VALID=true'], hint: 'CHECKSUM_VALID=' },
  { name: 'all-original-needed', text: lines(160, i => `record ${i}: ${createHash('sha256').update(`recovery-${i}`).digest('hex')}`), facts: ['07541'], full: true },
  { name: 'pathological-unknown', text: 'x'.repeat(5000) + '\nSTATUS=unknown-count\n', facts: ['STATUS=unknown-count'], hint: 'STATUS=' },
];
// This scenario's oracle is every byte; no fact derived from the produced preview.
fixtures.find(f => f.full).facts = [];
const count = text => { try { return economyTokens(text); } catch (e) { if (String(e).includes('Exact token count unavailable')) return null; throw e; } };
const sum = values => values.some(v => v === null) ? null : values.reduce((a, b) => a + b, 0);
const diff = (a, b) => a === null || b === null ? null : a - b;
const rpc = (id, method, params) => ({ jsonrpc: '2.0', id, method, ...(params === undefined ? {} : { params }) });
const reply = (id, result) => ({ jsonrpc: '2.0', id, result });
const toolReply = (id, text, isError = false) => reply(id, { content: [{ type: 'text', text }], isError });
const wireTokens = value => count(JSON.stringify(value) + '\n');
const initialize = instructions => reply(1, { protocolVersion: '2024-11-05', capabilities: { tools: {} }, serverInfo: { name: 'julius', version: '0.23.1' }, instructions });
const interfaceTokens = (tools, instructions) => sum([
  wireTokens(rpc(1, 'initialize', { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'offline-benchmark', version: '1' } })),
  wireTokens(initialize(instructions)), wireTokens({ jsonrpc: '2.0', method: 'notifications/initialized' }),
  wireTokens(rpc(2, 'tools/list')), wireTokens(reply(2, { tools })),
]);
const inheritedInterface = interfaceTokens(TOOLS, mcpInstructions());
const compactInterface = interfaceTokens(COMPACT_TOOLS, COMPACT_INSTRUCTIONS);
const scratch = mkdtempSync(join(tmpdir(), 'julius-economy-benchmark-'));
try {
  const results = [];
  for (const fixture of fixtures) {
    const root = join(scratch, fixture.name); mkdirSync(root); const economy = new Economy(root);
    let id = 3; const discoveryCosts = [];
    for (const args of [{}, { operation: 'julius_find_code' }]) {
      const r = await callCompact(root, 'julius_discover', args); assert.equal(r.isError, false);
      discoveryCosts.push(wireTokens(rpc(id, 'tools/call', { name: 'julius_discover', arguments: args })), wireTokens(toolReply(id++, r.text)));
    }
    const budget = 400;
    const rawOutputTokens = count(fixture.text);
    const compactRequest = wireTokens(rpc(id, 'tools/call', { name: 'julius_call', arguments: { operation: 'julius_find_code', args: { query: fixture.name }, budget } }));
    const inheritedRequest = wireTokens(rpc(id, 'tools/call', { name: 'julius_find_code', arguments: { query: fixture.name } }));
    // Frozen outputs substitute for graph execution here, so neither engine nor
    // any external command is executed twice to obtain a counterfactual.
    const captured = await economy.capture(fixture.text, { budget });
    const visibleResponse = wireTokens(toolReply(id, captured.text, fixture.name === 'middle-failure'));
    const rawResponse = wireTokens(toolReply(id++, fixture.text, fixture.name === 'middle-failure'));
    const followups = []; let observed = captured.text;
    const retrieve = async args => {
      const r = await callCompact(root, 'julius_call', { operation: 'context.read', args, budget });
      assert.equal(r.isError, false, r.text);
      followups.push(wireTokens(rpc(id, 'tools/call', { name: 'julius_call', arguments: { operation: 'context.read', args, budget } })), wireTokens(toolReply(id++, r.text)));
      observed += '\n' + r.text; return JSON.parse(r.text);
    };
    const missing = fixture.facts.filter(fact => !observed.includes(fact));
    if (missing.length || fixture.full) {
      const args = { operation: 'context.read' }; const schema = await callCompact(root, 'julius_discover', args);
      discoveryCosts.push(wireTokens(rpc(id, 'tools/call', { name: 'julius_discover', arguments: args })), wireTokens(toolReply(id++, schema.text)));
      assert.ok(captured.handle);
    }
    if (missing.length) { assert.ok(fixture.hint); await retrieve({ handle: captured.handle, search: fixture.hint }); }
    for (const fact of fixture.facts) assert.ok(observed.includes(fact), `${fixture.name}: missing independent fact ${fact}`);
    if (fixture.full) {
      const parts = []; let start = 0;
      while (start < Buffer.byteLength(fixture.text)) {
        const r = await retrieve({ handle: captured.handle, start }); assert.ok(r.end > start, 'retrieval must advance');
        parts.push(Buffer.from(r.content, r.format === 'base64' ? 'base64' : 'utf8')); start = r.end;
      }
      assert.deepEqual(Buffer.concat(parts), Buffer.from(fixture.text));
    }
    // Local integrity verification is not sent to an agent and is not counted as
    // delivered protocol. The full-needed scenario above counts actual recovery.
    const recovered = captured.handle ? (await economy.read(captured.handle, { budget: 1000000, raw: true })).bytes : captured.bytes;
    assert.deepEqual(recovered, Buffer.from(fixture.text));
    const inheritedTotal = sum([inheritedInterface, inheritedRequest, rawResponse]);
    const juliusTotal = sum([compactInterface, ...discoveryCosts, compactRequest, visibleResponse, ...followups]);
    results.push({ name: fixture.name, sha256: createHash('sha256').update(fixture.text).digest('hex'), bytes: Buffer.byteLength(fixture.text), requiredFacts: fixture.facts, retrievalHint: fixture.hint ?? null,
      factsVerified: true, roundTripVerified: true, rawOutputTokens,
      inheritedStyle: { initialInterfaceTokens: inheritedInterface, requestTokens: inheritedRequest, responseTokens: rawResponse, totalTokens: inheritedTotal },
      julius: { initialInterfaceTokens: compactInterface, discoveryTokens: sum(discoveryCosts), requestTokens: compactRequest, textTokens: count(captured.text), responseTokens: visibleResponse, followupTokens: sum(followups), followupCalls: followups.length / 2, totalTokens: juliusTotal },
      differenceVsRawOutput: diff(rawOutputTokens, juliusTotal), differenceVsInheritedStyle: diff(inheritedTotal, juliusTotal) });
  }
  assert.ok(results.find(f => f.name === 'all-original-needed').differenceVsInheritedStyle < 0);
  assert.equal(results.find(f => f.name === 'pathological-unknown').rawOutputTokens, null);
  const report = { version: 1, command: 'npm run build && npm run benchmark:economy', encoding: ECONOMY_ENCODING,
    baseline: 'Inherited-style Julius six-tool definitions and initialization instructions, derived from Trail-Code b1211efd3eef0efa121b93800e5dd8e547aead77. Not an execution of the upstream binary.',
    method: 'Fixed tool-output fixtures at the graph-result boundary. One fresh protocol session per fixture, exact JSON-RPC NDJSON initialization, schemas, discovery requests/responses, invocation requests, result wrappers and retrieval. No structuredContent duplication. Local byte-integrity checks are not agent deliveries. Full-needed retrieval is counted. Unknown counts propagate as null.',
    limitations: 'No model calls, API billing, coding-task accuracy or live host compatibility measured. Graph/source-like fixtures do not evaluate retrieval relevance. Transport tokens are a named-encoding proxy for visible protocol, not any provider-specific message serialization.',
    providerUsage: null, providerCost: null, codingTaskAccuracy: null, fixtures: results };
  const output = JSON.stringify(report, null, 2) + '\n';
  if (process.argv.includes('--write')) writeFileSync(new URL('../docs/economy-benchmark.json', import.meta.url), output);
  process.stdout.write(output);
} finally { rmSync(scratch, { recursive: true, force: true }); }
