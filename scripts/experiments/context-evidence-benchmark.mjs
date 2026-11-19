import assert from 'node:assert/strict';
import { spawn, execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { once } from 'node:events';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { ECONOMY_ENCODING, economyTokens } from '../../dist/economy/index.js';
import { repoPlace } from '../../dist/notes/home.js';
import { cases } from './context-evidence-cases.mjs';

const cli = fileURLToPath(new URL('../../dist/bin/julius.js', import.meta.url));
const onlyBaseline = process.argv.includes('--baseline-only');
const scratch = mkdtempSync(join(tmpdir(), 'julius-context-benchmark-'));
const wire = value => `${JSON.stringify(value)}\n`;
const count = text => {
  try { return economyTokens(text); }
  catch (error) { if (error.message.startsWith('Exact token count unavailable')) return null; throw error; }
};
const sum = values => values.includes(null) ? null : values.reduce((total, value) => total + value, 0);

function put(path, content) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, content);
}

function prepare(fixture, lane) {
  const repo = join(scratch, fixture.name, lane, 'repo');
  const home = join(scratch, fixture.name, lane, 'home');
  mkdirSync(repo, { recursive: true });
  mkdirSync(home, { recursive: true });
  execFileSync('git', ['init', '-q', repo]);
  const env = { ...process.env, HOME: home, USERPROFILE: home, JULIUS_HOME: join(home, '.julius'), XDG_CONFIG_HOME: join(home, '.config') };
  for (const [path, content] of Object.entries(fixture.files)) put(join(repo, path), content);
  if (fixture.personal) put(join(repoPlace(repo, env).dir, 'notes', 'personal.md'), fixture.personal);
  return { repo, env };
}

async function client(repo, env, run) {
  const child = spawn(process.execPath, [cli, 'mcp', repo], { env, stdio: ['pipe', 'pipe', 'pipe'] });
  const exited = once(child, 'close');
  const output = createInterface({ input: child.stdout })[Symbol.asyncIterator]();
  const record = [];
  let id = 0;
  let errors = '';
  child.stderr.on('data', data => { errors += data; });
  const request = async (method, params, phase) => {
    const json = wire({ jsonrpc: '2.0', id: ++id, method, params });
    child.stdin.write(json);
    const reply = await output.next();
    assert.ok(!reply.done, errors || 'MCP closed before responding');
    const parsed = JSON.parse(reply.value);
    assert.equal(parsed.id, id);
    assert.ok(parsed.result && !parsed.result.isError, JSON.stringify(parsed));
    record.push({ phase, request: json, response: `${reply.value}\n` });
    return parsed.result;
  };
  const notify = (method, phase) => {
    const request = wire({ jsonrpc: '2.0', method });
    child.stdin.write(request);
    record.push({ phase, request, response: '' });
  };
  const timeout = setTimeout(() => child.kill(), 45_000);
  try { return await run({ request, notify, record }); }
  finally { clearTimeout(timeout); child.stdin.end(); child.kill(); await exited; }
}

function visible(value) {
  if (!value.startsWith('{')) return value;
  const { content, format } = JSON.parse(value);
  return format === 'utf8' ? content : '';
}

function pilotFacts(text, fixture) {
  const found = new Set();
  let source;
  let line = 0;
  for (const row of text.split('\n')) {
    const heading = /^(code|note) ("(?:[^"\\]|\\.)*") (?:body )?L(\d+)(?:-L\d+)?(?: under .*|)$/.exec(row);
    if (heading) {
      const path = JSON.parse(heading[2]);
      const original = fixture.files[path];
      assert.ok(original, `Unknown pilot source: ${path}`);
      source = { path, lines: (heading[1] === 'note' ? original.split('\n---\n')[1].trim() : original).split('\n') };
      line = Number(heading[3]);
    } else if (row.startsWith('| ')) {
      const excerpt = row.slice(2);
      assert.equal(excerpt, source?.lines[line++ - 1], `Inexact excerpt from ${source?.path}`);
      fixture.facts.forEach((fact, index) => { if (fact.path === source.path && fact.text === excerpt) found.add(index); });
    }
  }
  return found;
}

function baselineFacts(text, fixture) {
  const found = new Set();
  fixture.facts.forEach((fact, index) => {
    // The inherited renderer strips note bullet markers from displayed leads.
    if (text.includes(fact.path) && text.includes(fact.text.replace(/^- /, ''))) found.add(index);
  });
  return found;
}

async function evaluate(fixture, lane) {
  const { repo, env } = prepare(fixture, lane);
  const pilot = lane === 'pilot';
  const value = await client(repo, env, async ({ request, notify, record }) => {
    const start = performance.now();
    const tool = async (name, args, phase) => (await request('tools/call', { name, arguments: args }, phase)).content[0].text;
    const discover = operation => tool('julius_discover', operation ? { operation } : {}, 'discovery');
    const find = () => tool('julius_call', { operation: 'julius_find_code', budget: fixture.budget,
      args: { query: fixture.query, ...(pilot ? { evidence: true } : {}) } }, 'query');
    await request('initialize', { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'context-evidence-benchmark', version: '1' } }, 'setup');
    notify('notifications/initialized', 'setup');
    await request('tools/list', undefined, 'setup');
    await discover();
    await discover('julius_find_code');
    const initial = await find();
    const firstMs = performance.now() - start;
    assert.ok(economyTokens(initial) <= fixture.budget);
    const first = visible(initial);
    let all = first;
    const check = pilot ? pilotFacts : baselineFacts;
    const initialFacts = check(first, fixture);
    const found = new Set(initialFacts);
    const handle = initial.match(/sha256:[0-9a-f]{64}/)?.[0];
    let retained;
    const read = async (phase) => {
      const reply = await tool('julius_call', { operation: 'context.read', delivery: 'complete', args: { handle } }, phase);
      const newline = reply.indexOf('\n');
      const body = reply.slice(newline + 1);
      assert.equal(JSON.parse(reply.slice(0, newline)).start, 0);
      assert.equal(`sha256:${createHash('sha256').update(body).digest('hex')}`, handle);
      retained = body;
      return body;
    };
    if (found.size < fixture.facts.length && handle) {
      await discover('context.read');
      all = await read('recovery');
      for (const index of check(all, fixture)) found.add(index);
    }
    const missing = fixture.facts.filter((_, index) => !found.has(index));
    // A host can read exact repo files when the MCP response exposes a path.
    // Model that local read explicitly because main retains only formatted note leads.
    for (const path of new Set(missing.map(fact => fact.path))) {
      if (!all.includes(path)) continue;
      const content = readFileSync(join(repo, path), 'utf8');
      record.push({ phase: 'local-read', request: wire({ method: 'readFile', path }), response: wire({ path, content }) });
      fixture.facts.forEach((fact, index) => { if (fact.path === path && content.split('\n').includes(fact.text)) found.add(index); });
    }
    const totalMs = performance.now() - start;
    const delivery = [...record];
    if (pilot && handle && !retained) retained = await read('audit');
    if (pilot) {
      const available = pilotFacts(retained ?? first, fixture);
      const absent = fixture.facts.filter((_, index) => !available.has(index));
      assert.deepEqual(absent, [], `${fixture.name}: evidence missing from retained sources\n${retained ?? first}`);
      if (fixture.requiresRecovery) assert.ok(retained && initialFacts.size < fixture.facts.length, 'fixture must require handle recovery');
      if (fixture.duplicate) assert.equal(first.split(fixture.duplicate).length - 1, 1);
    }
    for (const text of [first, all, retained ?? '']) {
      for (const deny of [...(fixture.forbidden ?? []), ...(pilot ? fixture.pilotForbidden ?? [] : [])]) assert.ok(!text.includes(deny), `${fixture.name}: exposed ${deny}`);
    }
    const costs = phase => sum(delivery.filter(item => !phase || phase === item.phase).flatMap(({ request, response }) => [count(request), count(response)]));
    return { firstFacts: initialFacts.size, finalFacts: found.size, initialTextTokens: count(initial), totalTokens: costs(), setupTokens: costs('setup'), discoveryTokens: costs('discovery'), calls: delivery.filter(item => item.phase !== 'setup').length, recoveryCalls: delivery.filter(item => item.phase === 'recovery' || item.phase === 'local-read').length, firstMs, totalMs };
  });
  return value;
}

try {
  const results = [];
  for (const [index, fixture] of cases.entries()) {
    const lanes = onlyBaseline ? ['baseline'] : index % 2 ? ['pilot', 'baseline'] : ['baseline', 'pilot'];
    const row = { name: fixture.name, budget: fixture.budget, facts: fixture.facts.length };
    for (const lane of lanes) row[lane] = await evaluate(fixture, lane);
    results.push(row);
  }
  const aggregate = lane => Object.fromEntries(['firstFacts', 'finalFacts', 'initialTextTokens', 'totalTokens', 'discoveryTokens', 'calls', 'recoveryCalls'].map(key => [key, sum(results.map(row => row[lane][key]))]));
  const baseline = aggregate('baseline');
  const pilot = onlyBaseline ? null : aggregate('pilot');
  const gate = pilot && pilot.totalTokens !== null && baseline.totalTokens !== null
    && pilot.totalTokens <= baseline.totalTokens * 0.90
    && results.every(row => row.pilot.finalFacts === row.facts && row.pilot.firstFacts >= row.baseline.firstFacts)
    && results.filter(row => row.pilot.firstFacts === row.facts && row.baseline.firstFacts < row.facts).length >= 2;
  console.log(JSON.stringify({ encoding: ECONOMY_ENCODING, providerUsage: null, baseline, pilot, gate, results }, null, 2));
  if (!onlyBaseline && !gate) process.exitCode = 1;
} finally { rmSync(scratch, { recursive: true, force: true }); }
