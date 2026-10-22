import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync, spawn } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'julius install space ')); const home = join(root, 'home'); const repo = join(root, 'repo');
  mkdirSync(join(home, '.claude'), { recursive: true }); mkdirSync(join(home, '.cursor')); mkdirSync(repo);
  const env = { ...process.env, HOME: home, USERPROFILE: home, XDG_CONFIG_HOME: join(home, '.config') };
  const cli = (...args: string[]) => spawnSync(process.execPath, ['--import', import.meta.resolve('tsx'), resolve('src/cli.ts'), ...args], { cwd: repo, env, encoding: 'utf8' });
  const claude = join(home, '.claude.json'); const cursor = join(home, '.cursor', 'mcp.json');
  return { root, home, repo, env, cli, claude, cursor, close: () => rmSync(root, { recursive: true, force: true }) };
}

test('global setup dry-run, idempotence, stable launch and exact uninstall', () => {
  const f = fixture();
  try {
    const original = '{ "theme": "dark", "mcpServers": {"other":{"command":"other"}, "julius":{"command":"old"}} }\n';
    writeFileSync(f.claude, original);
    let r = f.cli('install', '--hosts', 'claude,cursor', '--dry-run'); assert.equal(r.status, 0, r.stderr);
    assert.match(r.stdout, /\.claude.json/); assert.equal(readFileSync(f.claude, 'utf8'), original); assert.equal(existsSync(f.cursor), false);
    r = f.cli('install', '--hosts', 'claude,cursor'); assert.equal(r.status, 0, r.stderr);
    const installed = readFileSync(f.claude, 'utf8'); const entry = JSON.parse(installed).mcpServers.julius;
    assert.equal(entry.command, process.execPath); assert.equal(entry.args.at(-1), 'mcp'); assert.ok(entry.args[0].replaceAll('\\', '/').endsWith('/dist/bin/julius.js')); assert.ok(existsSync(entry.args[0]));
    assert.equal(JSON.stringify(entry).includes(f.repo), false);
    r = f.cli('install', '--hosts', 'claude,cursor'); assert.equal(r.status, 0, r.stderr); assert.equal(readFileSync(f.claude, 'utf8'), installed);
    r = f.cli('uninstall', '--global'); assert.equal(r.status, 0, r.stderr); assert.equal(readFileSync(f.claude, 'utf8'), original); assert.equal(existsSync(f.cursor), false);
    assert.equal(f.cli('uninstall', '--global').status, 0);
  } finally { f.close(); }
});

test('uninstall preserves foreign edits but rejects owned edits atomically', () => {
  const f = fixture();
  try {
    assert.equal(f.cli('install', '--hosts', 'claude,cursor').status, 0);
    const settings = JSON.parse(readFileSync(f.claude, 'utf8')); settings.theme = 'light'; writeFileSync(f.claude, JSON.stringify(settings));
    const cursor = JSON.parse(readFileSync(f.cursor, 'utf8')); cursor.mcpServers.julius.args.push('--full-tools'); writeFileSync(f.cursor, JSON.stringify(cursor));
    const r = f.cli('uninstall', '--global'); assert.notEqual(r.status, 0); assert.match(r.stderr, /conflict/i); assert.ok(JSON.parse(readFileSync(f.claude, 'utf8')).mcpServers.julius);
    cursor.mcpServers.julius.args.pop(); writeFileSync(f.cursor, JSON.stringify(cursor));
    assert.equal(f.cli('uninstall', '--global').status, 0);
    assert.deepEqual(JSON.parse(readFileSync(f.claude, 'utf8')), { theme: 'light' });
  } finally { f.close(); }
});

test('explicit migration preserves originals, avoids duplicate verified wiring and rejects conflicting copy', () => {
  const f = fixture();
  try {
    mkdirSync(join(f.repo, '.trail', 'learnings'), { recursive: true });
    const original = join(f.repo, '.trail', 'learnings', 'lesson.md'); writeFileSync(original, 'Never repeat side effects.\r\n');
    writeFileSync(f.claude, JSON.stringify({ mcpServers: { trail: { command: 'npx', args: ['-y', '@trailhq/trail-code', 'mcp'] }, 'trail-other': { command: 'unrelated' } } }));
    let r = f.cli('install', '--hosts', 'claude', '--migrate-trail', f.repo); assert.equal(r.status, 0, r.stderr);
    assert.equal(readFileSync(join(f.repo, '.julius', 'learnings', 'lesson.md'), 'utf8'), readFileSync(original, 'utf8'));
    assert.equal(JSON.parse(readFileSync(f.claude, 'utf8')).mcpServers.trail, undefined);
    assert.ok(JSON.parse(readFileSync(f.claude, 'utf8')).mcpServers['trail-other']);
    assert.equal(f.cli('install', '--hosts', 'claude', '--migrate-trail', f.repo).status, 0);
    writeFileSync(join(f.repo, '.julius', 'learnings', 'lesson.md'), 'different');
    r = f.cli('install', '--hosts', 'claude', '--migrate-trail', f.repo); assert.notEqual(r.status, 0); assert.match(r.stderr, /conflict/i);
    assert.equal(readFileSync(original, 'utf8'), 'Never repeat side effects.\r\n');
  } finally { f.close(); }
});

test('Codex TOML install owns only its section and preserves later unrelated edits', () => {
  const f = fixture();
  try {
    mkdirSync(join(f.home, '.codex')); const path = join(f.home, '.codex', 'config.toml');
    const original = 'model = "example"\n\n[mcp_servers.other]\ncommand = "other"\n\n[mcp_servers.julius]\ncommand = "old"\nargs = []\n';
    writeFileSync(path, original);
    let r = f.cli('install', '--hosts', 'codex'); assert.equal(r.status, 0, r.stderr);
    const installed = readFileSync(path, 'utf8'); assert.match(installed, /julius\.js/);
    assert.equal(f.cli('install', '--hosts', 'codex').status, 0); assert.equal(readFileSync(path, 'utf8'), installed);
    assert.equal(f.cli('uninstall', '--global').status, 0); assert.equal(readFileSync(path, 'utf8'), original);
    assert.equal(f.cli('install', '--hosts', 'codex').status, 0);
    writeFileSync(path, readFileSync(path, 'utf8').replace('model = "example"', 'model = "changed"') + '\n[features]\nfoo = true\n');
    assert.equal(f.cli('uninstall', '--global').status, 0);
    const result = readFileSync(path, 'utf8'); assert.match(result, /model = "changed"/); assert.match(result, /foo = true/); assert.match(result, /command = "old"/);
  } finally { f.close(); }
});

test('transaction failure rolls back exact bytes including migration and preserves concurrent foreign edits', async () => {
  const { installGlobal } = await import('../src/hosts/install.js');
  const f = fixture();
  try {
    mkdirSync(join(f.home, '.codex')); const codex = join(f.home, '.codex', 'config.toml');
    const original = 'model="old"\r\n'; writeFileSync(codex, original); writeFileSync(f.claude, '{"theme":"dark"}');
    assert.throws(() => installGlobal({ home: f.home, hosts: ['claude', 'codex', 'cursor'], afterWrite: (_path, n) => { if (n === 2) throw new Error('injected failure'); } }), /injected failure/);
    assert.equal(readFileSync(codex, 'utf8'), original); assert.equal(readFileSync(f.claude, 'utf8'), '{"theme":"dark"}'); assert.equal(existsSync(f.cursor), false);
    assert.equal(existsSync(join(f.home, '.julius', 'install', 'manifest.json')), false);
    assert.throws(() => installGlobal({ home: f.home, hosts: ['claude', 'cursor'], afterWrite: (path, n) => {
      if (n === 1) { const changed = JSON.parse(readFileSync(path, 'utf8')); changed.foreign = true; writeFileSync(path, JSON.stringify(changed)); throw new Error('injected concurrent edit'); }
    } }), /Rollback conflict/);
    assert.equal(JSON.parse(readFileSync(f.claude, 'utf8')).foreign, true);
    assert.equal(existsSync(join(f.home, '.julius', 'install', 'transaction.json')), true, 'recovery evidence retained');
  } finally { f.close(); }
});

test('setup rejects invalid config, unknown hosts and owned TOML changes without touching siblings', () => {
  const f = fixture();
  try {
    writeFileSync(f.claude, 'not json'); assert.notEqual(f.cli('install', '--hosts', 'cursor,claude').status, 0); assert.equal(existsSync(f.cursor), false);
    assert.notEqual(f.cli('install', '--hosts', 'unknown').status, 0);
    mkdirSync(join(f.home, '.codex')); const path = join(f.home, '.codex', 'config.toml');
    assert.equal(f.cli('install', '--hosts', 'codex').status, 0);
    writeFileSync(path, readFileSync(path, 'utf8').replace('"mcp"', '"unexpected"'));
    const r = f.cli('uninstall', '--global'); assert.notEqual(r.status, 0); assert.match(r.stderr, /conflict/);
    assert.match(readFileSync(path, 'utf8'), /unexpected/);
  } finally { f.close(); }
});

test('installed launch command serves the actual second repository without init or a loader', async () => {
  const f = fixture();
  try {
    assert.equal(f.cli('install', '--hosts', 'claude').status, 0);
    const entry = JSON.parse(readFileSync(f.claude, 'utf8')).mcpServers.julius;
    const second = join(f.root, 'second repo'); mkdirSync(second);
    writeFileSync(join(second, 'feature.ts'), 'export function secondRepositoryOnly() { return 42; }\n');
    const child = spawn(entry.command, entry.args, { cwd: second, env: f.env, stdio: ['pipe', 'pipe', 'pipe'] });
    try {
      const result = await new Promise<any>((resolveReply, reject) => {
        let buffer = '', stderr = '';
        const timeout = setTimeout(() => reject(new Error(`launch timeout: ${stderr}`)), 30000);
        child.stderr.on('data', d => { stderr += d; });
        child.on('error', e => { clearTimeout(timeout); reject(e); });
        child.stdout.on('data', d => {
          buffer += d;
          const end = buffer.indexOf('\n');
          if (end >= 0) { clearTimeout(timeout); resolveReply(JSON.parse(buffer.slice(0, end))); }
        });
        child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'julius_call', arguments: { operation: 'julius_file_api', args: { file: 'feature.ts' } } } }) + '\n');
      });
      assert.equal(result.result.isError, false, JSON.stringify(result)); assert.match(result.result.content[0].text, /secondRepositoryOnly/);
      assert.equal(existsSync(join(second, '.julius', 'cache')), true); assert.equal(existsSync(join(f.repo, '.julius', 'cache')), false);
    } finally { const exited = new Promise<void>(r => child.once('exit', () => r())); child.kill(); await exited; }
  } finally { f.close(); }
});

test('reinstall after foreign edits preserves them on the following uninstall', () => {
  const f = fixture();
  try {
    assert.equal(f.cli('install', '--hosts', 'claude').status, 0);
    const config = JSON.parse(readFileSync(f.claude, 'utf8')); config.userPreference = 'keep'; writeFileSync(f.claude, JSON.stringify(config));
    assert.equal(f.cli('install', '--hosts', 'claude').status, 0);
    assert.equal(f.cli('uninstall', '--global').status, 0);
    assert.equal(JSON.parse(readFileSync(f.claude, 'utf8')).userPreference, 'keep');
  } finally { f.close(); }
});

test('Codex setup refuses malformed or multiline ambiguous TOML without writing', () => {
  const f = fixture();
  try {
    mkdirSync(join(f.home, '.codex')); const path = join(f.home, '.codex', 'config.toml');
    for (const original of ['invalid toml here', 'note = """\n[mcp_servers.julius]\ncommand = "innocent text"\n"""\n']) {
      writeFileSync(path, original); const r = f.cli('install', '--hosts', 'codex');
      assert.notEqual(r.status, 0); assert.equal(readFileSync(path, 'utf8'), original);
    }
  } finally { f.close(); }
});

test('migration removes verified repository MCP wiring and restores it on uninstall', () => {
  const f = fixture();
  try {
    const path = join(f.repo, '.mcp.json'); const original = JSON.stringify({ mcpServers: { trail: { command: 'trail', args: ['mcp'] }, custom: { command: 'custom' } } }); writeFileSync(path, original);
    const r = f.cli('install', '--hosts', 'claude', '--migrate-trail', f.repo); assert.equal(r.status, 0, r.stderr);
    assert.equal(JSON.parse(readFileSync(path, 'utf8')).mcpServers.trail, undefined);
    assert.ok(JSON.parse(readFileSync(path, 'utf8')).mcpServers.custom);
    assert.equal(f.cli('uninstall', '--global').status, 0); assert.equal(readFileSync(path, 'utf8'), original);
  } finally { f.close(); }
});

test('Codex migration removes only exact legacy MCP launch tables', () => {
  const f = fixture();
  try {
    mkdirSync(join(f.home, '.codex')); const path = join(f.home, '.codex', 'config.toml');
    const original = '[mcp_servers.trail]\ncommand = "trail"\nargs = ["mcp"]\n\n[mcp_servers.graft]\ncommand = "custom"\nargs = []\n'; writeFileSync(path, original);
    const r = f.cli('install', '--hosts', 'codex', '--migrate-trail', f.repo); assert.equal(r.status, 0, r.stderr);
    assert.doesNotMatch(readFileSync(path, 'utf8'), /\[mcp_servers.trail\]/); assert.match(readFileSync(path, 'utf8'), /command = "custom"/);
    assert.equal(f.cli('uninstall', '--global').status, 0); assert.equal(readFileSync(path, 'utf8'), original);
  } finally { f.close(); }
});


test('Codex setup rejects valid TOML whose existing namespace conflicts with the generated table', () => {
  const f = fixture();
  try {
    mkdirSync(join(f.home, '.codex')); const path = join(f.home, '.codex', 'config.toml');
    for (const original of ['"mcp_servers".julius.command = "old"\n', 'mcp_servers = false\n']) {
      writeFileSync(path, original);
      const result = f.cli('install', '--hosts', 'claude,codex');
      assert.notEqual(result.status, 0, 'must refuse an invalid merged TOML document');
      assert.equal(readFileSync(path, 'utf8'), original);
      assert.equal(existsSync(f.claude), false, 'preflight must finish before sibling writes');
    }
  } finally { f.close(); }
});


test('a manifest changed during planning prevents stale ownership from replacing the newer install', async () => {
  const { installGlobal, uninstallGlobal } = await import('../src/hosts/install.js');
  const f = fixture();
  try {
    // Pause outer planning at host iteration after its manifest was loaded.
    // This models another process completing a transaction before we take the lock.
    const hosts = ['claude']; let iterations = 0;
    hosts[Symbol.iterator] = function* () {
      if (++iterations === 2) installGlobal({ home: f.home, hosts: ['cursor'] });
      yield 'claude';
    };
    assert.throws(() => installGlobal({ home: f.home, hosts }), /Concurrent configuration conflict/);
    assert.equal(existsSync(f.claude), false);
    assert.ok(JSON.parse(readFileSync(f.cursor, 'utf8')).mcpServers.julius);
    uninstallGlobal({ home: f.home });
    assert.equal(existsSync(f.cursor), false, 'newer transaction ownership remains usable');
  } finally { f.close(); }
});
