import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, symlinkSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { economyTokens } from '../../dist/economy/index.js';

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, '../..');
const work = resolve(process.argv[2]);
const frozen = resolve(process.argv[3]);
const output = resolve(process.argv[4] ?? 'docs/strategy/query-optimization');
const sha = x => createHash('sha256').update(x).digest('hex');
const json = (path, x) => { mkdirSync(dirname(path), { recursive: true }); writeFileSync(path, JSON.stringify(x, null, 2) + '\n'); };
function treeHash(root) {
  const rows = [];
  function visit(dir) { for (const e of readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    const path = join(dir, e.name);
    if (e.isDirectory()) visit(path); else if (e.isFile()) rows.push([relative(root, path), sha(readFileSync(path))]);
  } }
  visit(root); return sha(JSON.stringify(rows));
}
const candidate = join(work, 'candidate'); assert.ok(!existsSync(candidate), 'Use a fresh candidate directory');
mkdirSync(candidate, { recursive: true });
for (const path of ['dist', 'src', 'package.json', 'package-lock.json']) cpSync(join(repo, path), join(candidate, path), { recursive: true });
symlinkSync(join(repo, 'node_modules'), join(candidate, 'node_modules'));
const arms = { baseline: join(work, 'baseline'), candidate };
const runtimeHashes = Object.fromEntries(Object.entries(arms).map(([arm, path]) => [arm, treeHash(join(path, 'dist'))]));
const home = join(work, 'home'); mkdirSync(home, { recursive: true });
const guard = join(work, 'offline.log'); writeFileSync(guard, '');
const env = { PATH: process.env.PATH, HOME: home, USERPROFILE: home, CI: '1', DO_NOT_TRACK: '1', JULIUS_PROBE_GUARD_LOG: guard,
  NODE_OPTIONS: `--require=${join(here, 'offline-guard.cjs')} --require=${join(here, 'selective-index-resources.cjs')}` };
const specs = ['julius', 'click', 'commander', 'zod', 'synthetic-large'];
const report = { version: 1, date: new Date().toISOString(), node: process.version, runtimeHashes,
  harnessSha256: sha(readFileSync(fileURLToPath(import.meta.url))), workerSha256: sha(readFileSync(join(here, 'query-optimization-worker.mjs'))),
  baselineSourceSha256: treeHash(join(arms.baseline, 'src')), candidateSourceSha256: treeHash(join(candidate, 'src')),
  scope: 'Offline comparison of actual before/after builds on identical frozen corpus files from the selective-index pilot. Exact AskResult parity includes ranking, floating-point scores, pointers, source, metadata and coverage. Formatting may remove a snippet only if its full text already appears verbatim in the same hit code. Four alternating rounds per arm/corpus; warm API five queries times five passes per round; CLI three frozen queries per round, fresh processes with refresh disabled. Real MCP includes refresh, discovery, default bounded replies and complete suffix recovery; all NDJSON request/response tokens counted using cl100k_base, including one-time setup. No models or simulated agent decisions. Fresh process is not cold OS cache; one machine, uncontrolled CPU load. Synthetic graph has containment/import edges only. No provider measurement or task-success inference.',
  providerUsage: null, providerCost: null, agentCorrectness: null,
  gate: { exactResultParity: true, preserveEveryCodeExcerptAndPointer: true, positiveAggregateWireTokenReduction: true, minLargeWarmReduction: 0.2, maxRealWarmRegression: 0.05 }, corpora: [] };
json(join(output, 'plan.json'), report);
function run(product, corpus, mode, input) {
  return JSON.parse(execFileSync(process.execPath, ['--expose-gc', join(here, 'query-optimization-worker.mjs'), product, corpus, mode, input],
    { cwd: corpus, env, encoding: 'utf8', timeout: 120000, maxBuffer: 16 * 1024 * 1024 }));
}
async function mcp(product, corpus, cases) {
  const child = spawn(process.execPath, [join(product, 'dist/bin/julius.js'), 'mcp', corpus], { cwd: corpus, env, stdio: ['pipe', 'pipe', 'pipe'] });
  const pending = new Map(); let id = 0; let stderr = ''; let tokens = 0;
  child.stderr.on('data', chunk => { stderr += chunk; });
  const closed = new Promise(done => child.on('close', code => { for (const p of pending.values()) p.reject(new Error(`MCP exit ${code}: ${stderr}`)); done(code); }));
  createInterface({ input: child.stdout }).on('line', line => {
    tokens += economyTokens(line + '\n'); const result = JSON.parse(line); const p = pending.get(result.id);
    if (p) { pending.delete(result.id); result.error ? p.reject(new Error(JSON.stringify(result.error))) : p.resolve(result.result); }
  });
  function request(method, params) {
    const serial = ++id; const wire = JSON.stringify({ jsonrpc: '2.0', id: serial, method, params }) + '\n'; tokens += economyTokens(wire);
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { child.kill(); reject(new Error(`MCP timeout: ${method}`)); }, 60000);
      pending.set(serial, { resolve: x => { clearTimeout(timer); resolve(x); }, reject: x => { clearTimeout(timer); reject(x); } });
      child.stdin.write(wire);
    });
  }
  async function call(operation, args, delivery) {
    const result = await request('tools/call', { name: 'julius_call', arguments: { operation, args, ...(delivery ? { delivery } : {}) } });
    assert.ok(!result.isError, JSON.stringify(result)); return result.content[0].text;
  }
  const rows = []; const start = performance.now();
  try {
    await request('initialize', { protocolVersion: '2025-03-26', capabilities: {}, clientInfo: { name: 'query-optimization', version: '1' } });
    const notification = JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n';
    tokens += economyTokens(notification); child.stdin.write(notification);
    await request('tools/list', {});
    const discovered = await request('tools/call', { name: 'julius_discover', arguments: { operation: 'julius_find_code' } });
    assert.ok(!discovered.isError);
    const startupMs = performance.now() - start; const setupTokens = tokens;
    for (let pass = 0; pass < 3; pass++) for (const c of cases.slice(0, 3)) {
      const beforeTokens = tokens; const began = performance.now();
      const first = await call('julius_find_code', { query: c.query, limit: 8 });
      let body = first; let recoveryCalls = 0;
      let envelope;
      try { envelope = JSON.parse(first); } catch {}
      if (envelope?.handle) {
        body = envelope.content;
        if (envelope.next) {
          const next = await call('context.read', { handle: envelope.handle, start: envelope.next.start }, 'complete');
          const split = next.indexOf('\n'); const header = JSON.parse(next.slice(0, split));
          assert.equal(header.start, envelope.next.start);
          assert.equal(header.end, envelope.totalBytes);
          body += next.slice(split + 1); recoveryCalls++;
        }
        assert.equal(Buffer.byteLength(body), envelope.totalBytes);
        assert.equal(sha(body), envelope.handle.slice(7), 'Recovered evidence digest');
      }
      rows.push({ id: c.id, pass, elapsedMs: performance.now() - began, wireTokens: tokens - beforeTokens, recoveryCalls, bodyTokens: economyTokens(body) });
    }
    return { startupMs, setupTokens, totalWireTokens: tokens, rows };
  } finally { child.stdin.end(); await closed; }
}
for (const name of specs) {
  console.error(`Comparing ${name}`);
  const corpus = join(frozen, 'corpora', name);
  const all = join(frozen, `${name}-cases.json`); const timing = join(frozen, `${name}-timing.json`);
  const cases = JSON.parse(readFileSync(timing));
  const record = { id: name, parity: {}, warm: [], cli: [], mcp: {} };
  for (const [arm, product] of Object.entries(arms)) record.parity[arm] = run(product, corpus, 'parity', all);
  assert.deepEqual(record.parity.baseline.rows.map(r => r.hash), record.parity.candidate.rows.map(r => r.hash), `${name}: full result parity`);
  for (let round = 0; round < 4; round++) for (const [arm, product] of round % 2 ? Object.entries(arms).reverse() : Object.entries(arms)) {
    record.warm.push({ arm, round, ...run(product, corpus, 'warm', timing) });
    for (const c of cases.slice(0, 3)) {
      const resources = join(work, 'resources.json'); const start = performance.now();
      const result = JSON.parse(execFileSync(process.execPath, [join(product, 'dist/bin/julius.js'), 'ask', c.query, corpus, '--json', '--no-refresh'],
        { cwd: corpus, env: { ...env, JULIUS_SELECTIVE_RESOURCES: resources }, encoding: 'utf8', timeout: 60000 }));
      record.cli.push({ arm, round, id: c.id, elapsedMs: performance.now() - start, hash: sha(JSON.stringify(result)), ...JSON.parse(readFileSync(resources)) });
    }
  }
  for (let round = 0; round < 4; round++) {
    assert.deepEqual(record.warm.find(r => r.arm === 'baseline' && r.round === round).rows.map(r => r.hash), record.warm.find(r => r.arm === 'candidate' && r.round === round).rows.map(r => r.hash));
    assert.deepEqual(record.cli.filter(r => r.arm === 'baseline' && r.round === round).map(r => r.hash), record.cli.filter(r => r.arm === 'candidate' && r.round === round).map(r => r.hash));
  }
  for (const [arm, product] of Object.entries(arms)) record.mcp[arm] = await mcp(product, corpus, cases);
  report.corpora.push(record); json(join(output, 'report.json'), report);
}
for (const [arm, product] of Object.entries(arms)) assert.equal(treeHash(join(product, 'dist')), runtimeHashes[arm], 'Runtime changed');
assert.equal(readFileSync(guard, 'utf8'), '');
json(join(output, 'report.json'), report);
console.log('All ranking/source and recovery checks passed.');
