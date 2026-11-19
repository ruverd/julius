import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn, execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtempSync, mkdirSync, writeFileSync, existsSync, rmSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { once } from 'node:events';
import { economyTokens } from '../src/economy/index.js';

export function client(repo: string, full = false, dir?: string) {
  const home = mkdtempSync(join(tmpdir(), 'julius mcp home '));
  const child = spawn(process.execPath, ['--import', 'tsx', resolve('src/cli.ts'), ...(dir ? ['--dir', dir] : []), 'mcp', repo, ...(full ? ['--full-tools'] : [])], {
    env: { ...process.env, HOME: home, USERPROFILE: home, XDG_CONFIG_HOME: join(home, '.config') }, stdio: ['pipe', 'pipe', 'pipe'],
  });
  const waiting = new Map<number, { resolve: (r: any) => void; reject: (e: Error) => void }>();
  let serial = 0, buffer = '', errors = '';
  child.stderr.on('data', d => { errors += d; });
  child.stdout.on('data', d => {
    buffer += d;
    let end: number;
    while ((end = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, end); buffer = buffer.slice(end + 1);
      if (line) { const msg = JSON.parse(line); waiting.get(msg.id)?.resolve(msg); waiting.delete(msg.id); }
    }
  });
  child.on('exit', () => { for (const waiter of waiting.values()) waiter.reject(new Error(errors || 'MCP exited')); waiting.clear(); });
  return {
    async request(method: string, params?: object): Promise<any> {
      const id = ++serial;
      return new Promise((resolveReply, reject) => {
        const timer = setTimeout(() => { waiting.delete(id); reject(new Error(`MCP timeout: ${errors}`)); }, 30000);
        waiting.set(id, { resolve: r => { clearTimeout(timer); resolveReply(r); }, reject: e => { clearTimeout(timer); reject(e); } });
        child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
      });
    },
    async close() { child.kill(); if (child.exitCode === null) await once(child, 'exit'); rmSync(home, { recursive: true, force: true }); },
  };
}

test('compact protocol discovers, validates, captures, recovers and lazily builds a fresh repo', async () => {
  const repo = mkdtempSync(join(tmpdir(), 'julius fresh repo '));
  writeFileSync(join(repo, 'sum.ts'), 'export function add(a: number, b: number) { return a + b; }\n');
  const c = client(repo);
  try {
    const init = await c.request('initialize', { protocolVersion: '2024-11-05' });
    assert.match(init.result.instructions, /julius_discover/);
    const list = await c.request('tools/list');
    assert.deepEqual(list.result.tools.map((t: any) => t.name), ['julius_discover', 'julius_call']);
    const invalid = await c.request('tools/call', { name: 'julius_discover', arguments: null });
    assert.equal(invalid.result.isError, true);
    const discover = await c.request('tools/call', { name: 'julius_discover', arguments: {} });
    assert.match(discover.result.content[0].text, /context.capture/);
    assert.equal(existsSync(join(repo, '.julius', 'cache')), false);
    const content = 'alpha beta gamma\n'.repeat(1000) + 'REQUIRED_FACT=42\n';
    const capture = await c.request('tools/call', { name: 'julius_call', arguments: { operation: 'context.capture', args: { content }, budget: 300 } });
    assert.equal(capture.result.isError, false);
    assert.ok(economyTokens(capture.result.content[0].text) <= 300);
    const handle = JSON.parse(capture.result.content[0].text).handle;
    const read = await c.request('tools/call', { name: 'julius_call', arguments: { operation: 'context.read', args: { handle, search: 'REQUIRED_FACT' }, budget: 300 } });
    assert.match(read.result.content[0].text, /REQUIRED_FACT=42/);
    for (const args of [ { operation: 'exec', args: { command: 'touch forbidden' } }, { operation: 'julius_find_code', args: { query: 3 } }, { operation: 'context.read', args: { handle, raw: true } }, { operation: 'julius_repo_map', args: { max_dirs: -1 } } ]) {
      const r = await c.request('tools/call', { name: 'julius_call', arguments: args });
      assert.equal(r.result.isError, true, JSON.stringify(args));
    }
    assert.equal(existsSync(join(repo, '.julius', 'cache')), false, 'invalid calls do not build');
    const graph = await c.request('tools/call', { name: 'julius_call', arguments: { operation: 'julius_file_api', args: { file: 'sum.ts' }, budget: 500 } });
    assert.equal(graph.result.isError, false, graph.result.content[0].text);
    assert.match(graph.result.content[0].text, /add/);
    assert.equal(existsSync(join(repo, '.julius', 'cache')), true);
    const missing = await c.request('tools/call', { name: 'julius_call', arguments: { operation: 'julius_file_api', args: { file: 'missing.ts' } } });
    assert.equal(missing.result.isError, true);
  } finally { await c.close(); rmSync(repo, { recursive: true, force: true }); }
});

test('full tools require explicit compatibility mode', async () => {
  const repo = mkdtempSync(join(tmpdir(), 'julius full ')); const c = client(repo, true);
  try { const r = await c.request('tools/list'); assert.equal(r.result.tools.length, 6); }
  finally { await c.close(); rmSync(repo, { recursive: true, force: true }); }
});

test('opt-in evidence keeps source and note excerpts together and rebuilds after edits', async () => {
  const scratch = mkdtempSync(join(tmpdir(), 'julius combined evidence '));
  const repo = join(scratch, 'repo');
  mkdirSync(repo);
  execFileSync('git', ['init', '-q', repo]);
  const notes = join(repo, '.julius', 'learnings');
  mkdirSync(notes, { recursive: true });
  const long = 'Calibration evidence sequence 🌎: ' + 'ruby coral steel ink '.repeat(175).trim();
  const current = (status: string) => `---\ntitle: Calibration evidence sequence\nstatus: ${status}\n---\n\n## Decided\n- Calibration evidence sequence must be recorded in order.\n- ${long}\n`;
  const code = (n: number) => `const calibrationSeed = ${n};\nexport function calibrationSequence() { return calibrationSeed; }\n`;
  writeFileSync(join(notes, 'calibration.md'), current('active'));
  writeFileSync(join(repo, 'calibration.ts'), code(17));
  if (process.platform !== 'win32') {
    const outside = join(scratch, 'private.md');
    writeFileSync(outside, current('active').replaceAll('Calibration evidence sequence', 'Calibration OUTSIDE_PRIVATE evidence sequence'));
    symlinkSync(outside, join(notes, 'private.md'));
  }
  const c = client(repo);
  const call = async (args: object) => {
    const reply = await c.request('tools/call', { name: 'julius_call', arguments: args });
    const text = reply.result.content[0].text as string;
    assert.equal(reply.result.isError, false, text);
    return text;
  };
  const args = { operation: 'julius_find_code', args: { query: 'What is the calibration evidence sequence and what does calibrationSequence return?' }, budget: 256 };
  try {
    const first = await call({ ...args, args: { ...args.args, evidence: true } });
    assert.ok(economyTokens(first) <= args.budget);
    assert.match(first, /note "\.julius\/learnings\/calibration.md" body L2 under "## Decided"/);
    assert.match(first, /code "calibration.ts" L1-L2\n\| const calibrationSeed = 17;/);
    assert.ok(!first.includes(long));
    const handle = first.match(/sha256:[a-f0-9]{64}/)?.[0];
    assert.ok(handle);
    const recovery = await call({ operation: 'context.read', args: { handle }, delivery: 'complete' });
    const body = recovery.slice(recovery.indexOf('\n') + 1);
    assert.equal(`sha256:${createHash('sha256').update(body).digest('hex')}`, handle);
    assert.ok(body.includes(`| - ${long}`));
    assert.ok(!body.includes('OUTSIDE_PRIVATE'));
    const source = '.julius/learnings/calibration.md';
    const selector = { operation: 'context.read', args: { handle, evidence: { source, from: 3 } } };
    const exact = await call({ ...selector, delivery: 'complete' });
    const [header, ...rows] = exact.split('\n');
    const span = JSON.parse(header!);
    assert.deepEqual(span.evidence, { path: source, kind: 'note', from: 3, to: 3, heading: '## Decided' });
    assert.equal(rows.join('\n'), `| - ${long}`);
    assert.equal(Buffer.from(body).subarray(span.start, span.end).toString(), rows.join('\n'));
    const partial = JSON.parse(await call({ ...selector, budget: 256 }));
    assert.equal(partial.next.end, span.end, 'continuation stops at the selected passage');
    assert.deepEqual(JSON.parse(await call({ ...selector, budget: 256, args: { ...selector.args, format: 'lines' } })), partial);
    const compactExact = await call({ ...selector, budget: 256, args: { handle, format: 'lines', evidence: { source, from: 2 } } });
    assert.match(compactExact, /^evidence sha256:[a-f0-9]+\nsource 0 note /);
    assert.match(compactExact, /\n\| - Calibration evidence sequence must be recorded in order\.$/);
    const tail = await call({ operation: 'context.read', args: { handle, ...partial.next }, delivery: 'complete' });
    assert.equal(partial.content + tail.slice(tail.indexOf('\n') + 1), `| - ${long}`);
    const lookup = JSON.parse(await call({ operation: 'context.read', budget: 500, args: { handle,
      evidence: { query: 'calibration sequence evidence', exclude: [{ source, from: 3 }] },
    } }));
    assert.deepEqual(new Set(lookup.hits.map((hit: { evidence: { kind: string } }) => hit.evidence.kind)), new Set(['note', 'code']));
    assert.ok(lookup.hits.some((hit: { content: string }) => hit.content.includes('const calibrationSeed = 17')));
    for (const hit of lookup.hits) {
      assert.equal(Buffer.from(body).subarray(hit.start, hit.end).toString(), hit.content);
      assert.ok(!hit.content.includes(long));
    }
    const compact = await call({ operation: 'context.read', budget: 500, args: { handle, format: 'lines',
      evidence: { query: 'calibration sequence evidence', exclude: [{ source, from: 3 }] },
    } });
    assert.ok(compact.startsWith(`evidence ${handle}\n`));
    assert.ok(economyTokens(compact) < economyTokens(JSON.stringify(lookup)));
    assert.equal(compact.split('\n').filter(line => line.startsWith('hit ')).length, lookup.hits.length);
    for (const hit of lookup.hits) {
      assert.ok(compact.includes(` ${hit.start}\n${hit.content}`));
    }
    const incompatibleFormat = await c.request('tools/call', { name: 'julius_call', arguments: {
      operation: 'context.read', args: { handle, format: 'lines', start: 0 },
    } });
    assert.equal(incompatibleFormat.result.isError, true);
    for (const invalid of [{ source: 'private.md', from: 1 }, { source, from: 1000 }, { source, from: 3, to: 2 }]) {
      const reply = await c.request('tools/call', { name: 'julius_call', arguments: { ...selector, args: { handle, evidence: invalid } } });
      assert.equal(reply.result.isError, true);
      assert.doesNotMatch(reply.result.content[0].text, /OUTSIDE_PRIVATE|ruby coral/);
    }
    const inherited = await call(args);
    assert.doesNotMatch(inherited, /^Repository evidence/m);

    const focused = await call({ ...args, args: { evidence: true, evidenceScope: 'auto',
      query: 'In calibration.ts, what does calibrationSequence return?',
    } });
    assert.match(focused, /code "calibration.ts"/);
    assert.doesNotMatch(focused, /note "|More evidence/);
    const composed = await call({ ...args, args: { evidence: true, evidenceScope: 'auto',
      query: 'What did the calibration note decide and what does calibrationSequence return?',
    } });
    assert.match(composed, /note "\.julius\/learnings\/calibration.md"/);
    assert.match(composed, /code "calibration.ts"/);

    writeFileSync(join(repo, 'calibration.ts'), code(29));
    writeFileSync(join(notes, 'calibration.md'), current('retired'));
    const updated = await call({ ...args, args: { ...args.args, evidence: true } });
    assert.match(updated, /calibrationSeed = 29/);
    assert.doesNotMatch(updated, /calibrationSeed = 17|calibration\.md|OUTSIDE_PRIVATE/);
  } finally { await c.close(); rmSync(scratch, { recursive: true, force: true }); }
});


test('compact lazy initialization builds into an existing empty custom context directory', async () => {
  const repo = mkdtempSync(join(tmpdir(), 'julius custom context '));
  const dir = join(repo, 'custom-map'); mkdirSync(dir);
  writeFileSync(join(repo, 'feature.ts'), 'export function customContextSymbol() { return 42; }\n');
  const c = client(repo, false, dir);
  try {
    const response = await c.request('tools/call', { name: 'julius_call', arguments: {
      operation: 'julius_file_api', args: { file: 'feature.ts' },
    } });
    assert.equal(response.result.isError, false, response.result.content[0].text);
    assert.match(response.result.content[0].text, /customContextSymbol/);
    assert.equal(existsSync(join(repo, '.julius', 'cache')), false);
  } finally { await c.close(); rmSync(repo, { recursive: true, force: true }); }
});
