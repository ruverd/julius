import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';
import { economyTokens } from '../../dist/economy/index.js';

const here = dirname(fileURLToPath(import.meta.url));
const [workArg, frozenArg, outputArg] = process.argv.slice(2);
const work = resolve(workArg); const frozen = resolve(frozenArg); const output = resolve(outputArg);
const sha = x => createHash('sha256').update(x).digest('hex');
const arms = { baseline: join(work, 'baseline'), candidate: join(work, 'candidate') };
const guard = join(work, 'protocol-offline.log'); writeFileSync(guard, '');
const env = { PATH: process.env.PATH, HOME: join(work, 'home'), USERPROFILE: join(work, 'home'), CI: '1', DO_NOT_TRACK: '1',
  JULIUS_PROBE_GUARD_LOG: guard, NODE_OPTIONS: `--require=${join(here, 'offline-guard.cjs')}` };
const report = { harnessSha256: sha(readFileSync(fileURLToPath(import.meta.url))),
  scope: 'Three alternating session pairs per corpus on the final frozen builds. Actual stdio MCP with automatic freshness checks, discovery, default preview and complete suffix recovery. Unlike the first diagnostic, client tokenization is deferred until after each child exits, outside latency measurement. No model, provider or host agent. Warm excludes first pass; requests and responses retained in compressed traces. Same machine and uncontrolled OS cache/load; small samples remain diagnostic.',
  providerUsage: null, providerCost: null, agentCorrectness: null, corpora: [] };
const traces = [];
async function session(product, corpus, cases) {
  const child = spawn(process.execPath, [join(product, 'dist/bin/julius.js'), 'mcp', corpus], { cwd: corpus, env, stdio: ['pipe', 'pipe', 'pipe'] });
  let id = 0; let stderr = ''; const pending = new Map(); const events = [];
  child.stderr.on('data', chunk => { stderr += chunk; });
  const closed = new Promise(done => child.on('close', code => { for (const p of pending.values()) p.reject(new Error(`MCP exit ${code}: ${stderr}`)); done(code); }));
  createInterface({ input: child.stdout }).on('line', line => {
    events.push({ direction: 'response', wire: line + '\n' });
    const response = JSON.parse(line); const p = pending.get(response.id);
    if (p) { pending.delete(response.id); response.error ? p.reject(new Error(JSON.stringify(response.error))) : p.resolve(response.result); }
  });
  function request(method, params) {
    const serial = ++id; const wire = JSON.stringify({ jsonrpc: '2.0', id: serial, method, params }) + '\n';
    events.push({ direction: 'request', wire });
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { child.kill(); reject(new Error(`MCP timeout ${method}`)); }, 60000);
      pending.set(serial, { resolve: x => { clearTimeout(timer); resolve(x); }, reject: x => { clearTimeout(timer); reject(x); } });
      child.stdin.write(wire);
    });
  }
  async function call(operation, args, delivery) {
    const result = await request('tools/call', { name: 'julius_call', arguments: { operation, args, ...(delivery ? { delivery } : {}) } });
    assert.ok(!result.isError, JSON.stringify(result)); return result.content[0].text;
  }
  const rows = [];
  try {
    await request('initialize', { protocolVersion: '2025-03-26', capabilities: {}, clientInfo: { name: 'query-confirmation', version: '1' } });
    const wire = JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n';
    events.push({ direction: 'request', wire }); child.stdin.write(wire);
    await request('tools/list', {});
    const found = await request('tools/call', { name: 'julius_discover', arguments: { operation: 'julius_find_code' } }); assert.ok(!found.isError);
    for (let pass = 0; pass < 3; pass++) for (const c of cases.slice(0, 3)) {
      const begin = events.length; const started = performance.now();
      const first = await call('julius_find_code', { query: c.query, limit: 8 });
      let parsed; try { parsed = JSON.parse(first); } catch {}
      let body = parsed?.handle ? parsed.content : first; let recoveryCalls = 0;
      if (parsed?.next) {
        const tail = await call('context.read', { handle: parsed.handle, start: parsed.next.start }, 'complete');
        const split = tail.indexOf('\n'); const header = JSON.parse(tail.slice(0, split));
        assert.equal(header.start, parsed.next.start); assert.equal(header.end, parsed.totalBytes);
        body += tail.slice(split + 1); recoveryCalls++;
      }
      const elapsedMs = performance.now() - started;
      if (parsed?.handle) { assert.equal(Buffer.byteLength(body), parsed.totalBytes); assert.equal(sha(body), parsed.handle.slice(7)); }
      rows.push({ id: c.id, pass, elapsedMs, recoveryCalls, eventStart: begin, eventEnd: events.length });
    }
  } finally { child.stdin.end(); await closed; }
  for (const event of events) event.tokens = economyTokens(event.wire);
  for (const row of rows) row.wireTokens = events.slice(row.eventStart, row.eventEnd).reduce((n, e) => n + e.tokens, 0);
  return { rows, totalWireTokens: events.reduce((n, e) => n + e.tokens, 0), events };
}
for (const name of ['julius', 'click', 'commander', 'zod', 'synthetic-large']) {
  console.error(`Confirming MCP ${name}`);
  const cases = JSON.parse(readFileSync(join(frozen, `${name}-timing.json`))); const runs = [];
  for (let round = 0; round < 3; round++) for (const [arm, product] of round % 2 ? Object.entries(arms).reverse() : Object.entries(arms)) {
    const { events, ...run } = await session(product, join(frozen, 'corpora', name), cases);
    traces.push({ corpus: name, arm, round, events }); runs.push({ arm, round, ...run });
  }
  report.corpora.push({ id: name, runs });
  writeFileSync(join(output, 'protocol-confirmation.json'), JSON.stringify(report, null, 2) + '\n');
}
assert.equal(readFileSync(guard, 'utf8'), '');
writeFileSync(join(output, 'protocol-traces.json.gz'), gzipSync(JSON.stringify(traces) + '\n'));
console.log('Protocol confirmation and digest checks passed.');
