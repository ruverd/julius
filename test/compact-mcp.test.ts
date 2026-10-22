import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, existsSync, rmSync } from 'node:fs';
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
