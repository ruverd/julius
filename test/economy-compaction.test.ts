import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { Economy, economyTokens } from '../src/economy/index.js';
import { compactOutput } from '../src/economy/compact-output.js';
import { callCompact } from '../src/mcp/compact.js';

const pass = (i: number) => `# Subtest: case ${i}\nok ${i} - case ${i}\n  ---\n  duration_ms: 0.125\n  ...\n`;
const failure = 'not ok 401 - expired token\n  error: expected 403, received 200; do NOT retry\n  location: auth.test.ts:73\n';
const tap = Array.from({ length: 400 }, (_, i) => pass(i + 1)).join('') + failure + '# tests 401\n# fail 1\n';

test('opt-in capture preserves diagnostics and exact originals; default and fallback remain bounded', async () => {
  const root = mkdtempSync(join(tmpdir(), 'julius-compaction-'));
  try {
    const economy = new Economy(root);
    const baseline = await economy.capture(tap, { budget: 1200 });
    const selected = await economy.capture(tap, { budget: 1200, compact: 'tap' });
    assert.equal(JSON.parse(baseline.text).delivery, undefined);
    const envelope = JSON.parse(selected.text);
    assert.equal(envelope.delivery, 'compacted');
    assert.equal(envelope.compaction, 'tap');
    assert.equal(envelope.omittedDetail, true);
    assert.ok(envelope.content.includes(failure));
    assert.ok(envelope.content.includes('# fail 1'));
    assert.ok(economyTokens(selected.text) <= 1200);
    assert.equal(selected.handle, baseline.handle);
    assert.deepEqual((await economy.read(envelope.handle, { budget: null, raw: true })).bytes, Buffer.from(tap));
    const unique = Array.from({ length: 800 }, (_, i) => `INFO record=${i}\n`).join('');
    assert.equal((await economy.capture(unique, { budget: 300, compact: 'log' })).text,
      (await economy.capture(unique, { budget: 300 })).text);
    const largeDiagnostics = tap + failure.repeat(500);
    assert.equal((await economy.capture(largeDiagnostics, { budget: 300, compact: 'tap' })).text,
      (await economy.capture(largeDiagnostics, { budget: 300 })).text);
    const bytes = Buffer.from([255, 0, ...Buffer.from('ERROR\n'.repeat(200))]);
    const binary = await economy.capture(bytes, { budget: 300, compact: 'log' });
    assert.equal(JSON.parse(binary.text).format, 'base64');
    assert.deepEqual((await economy.read(binary.handle!, { budget: null, raw: true })).bytes, bytes);
    assert.equal((await economy.capture('ok\r\n', { budget: 300, compact: 'log' })).text, 'ok\r\n');
    await assert.rejects(economy.capture(tap, { budget: 1200, compact: 'tap', preview: () => '' }), /cannot be combined/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('production compactor keeps non-minimal TAP records and exact repeat order', () => {
  const warning = '# Subtest: warn\nok 2 - warn\n  ---\n  duration_ms: 1\n  warning: do NOT retry\n  ...\n';
  const skip = pass(3).replace('ok 3 - case 3', 'ok 3 - case 3 # SKIP offline');
  const nested = pass(4).split('\n').map(line => '    ' + line).join('\n');
  const text = pass(1).repeat(100) + warning + skip + nested + failure;
  const selected = compactOutput(text, 'tap');
  for (const exact of [warning, skip, nested, failure]) assert.ok(selected.text.includes(exact));
  const repeat = 'ERROR café 東京 🌱\r\n';
  assert.equal(compactOutput(repeat.repeat(100) + 'INFO reset\n' + repeat.repeat(50), 'log').text,
    repeat + '[previous exact line repeated 99 additional times]\nINFO reset\n' + repeat + '[previous exact line repeated 49 additional times]\n');
});

test('MCP exposes opt-in capture and keeps complete/focused delivery and recovery exact', async () => {
  const root = mkdtempSync(join(tmpdir(), 'julius-compaction-mcp-'));
  try {
    const discovery = await callCompact(root, 'julius_discover', { operation: 'context.capture' });
    assert.deepEqual(JSON.parse(discovery.text).inputSchema.properties.compact.enum, ['tap', 'log', 'build']);
    const invoke = (extra: object) => callCompact(root, 'julius_call', { operation: 'context.capture', args: { content: tap, compact: 'tap' }, ...extra });
    const selected = await invoke({ budget: 1200 });
    assert.equal(selected.isError, false, selected.text);
    const envelope = JSON.parse(selected.text);
    assert.equal(envelope.delivery, 'compacted');
    const recovered = await callCompact(root, 'julius_call', { operation: 'context.read', args: { handle: envelope.handle }, delivery: 'complete' });
    assert.equal(recovered.isError, false);
    assert.equal(recovered.text.slice(recovered.text.indexOf('\n') + 1), tap);
    const complete = await invoke({ delivery: 'complete' });
    assert.equal(complete.text.slice(complete.text.indexOf('\n') + 1), tap);
    const focused = await invoke({ focus: 'case 1', budget: 600 });
    assert.equal(JSON.parse(focused.text).delivery, 'targeted');
    assert.ok(JSON.parse(focused.text).content.includes('case 1'));
    const invalid = await callCompact(root, 'julius_call', { operation: 'context.capture', args: { content: 'ok', compact: 'json' } });
    assert.equal(invalid.isError, true);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('CLI run compacts once, preserves both streams and exit status, rejects invalid format before execution', () => {
  const root = mkdtempSync(join(tmpdir(), 'julius-compaction-cli-'));
  const env = { ...process.env, HOME: root, USERPROFILE: root, XDG_CONFIG_HOME: join(root, '.config') };
  const cli = (args: string[], input?: string) => spawnSync(process.execPath, ['--import', 'tsx', resolve('src/cli.ts'), ...args], { input, encoding: 'utf8', env });
  try {
    const captured = cli(['capture', '--repo', root, '--compact', 'tap', '--budget', '1200'], tap);
    assert.equal(captured.status, 0, captured.stderr);
    assert.equal(JSON.parse(captured.stdout).delivery, 'compacted');
    const script = `require('fs').appendFileSync('once', '1'); process.stdout.write(${JSON.stringify(tap)}); process.stderr.write(${JSON.stringify('ERROR café 東京 🌱\r\n')}); process.exitCode = 7`;
    const result = cli(['run', '--repo', root, '--compact', 'tap', '--budget', '1200', '--', process.execPath, '-e', script]);
    assert.equal(result.status, 7, result.stderr);
    assert.equal(readFileSync(join(root, 'once'), 'utf8'), '1');
    const envelope = JSON.parse(result.stdout);
    assert.equal(envelope.status, 7);
    assert.equal(envelope.compaction, 'tap');
    assert.ok(envelope.stdout.includes(failure));
    assert.ok(economyTokens(result.stdout) <= 1200);
    const recovered = cli(['read', envelope.stdoutHandle, '--repo', root, '--raw']);
    assert.equal(recovered.stdout, tap);
    assert.equal(cli(['read', envelope.stderrHandle, '--repo', root, '--raw']).stdout, 'ERROR café 東京 🌱\r\n');
    const invalid = cli(['run', '--repo', root, '--compact', 'json', '--', process.execPath, '-e', "require('fs').appendFileSync('once', '2')"]);
    assert.equal(invalid.status, 1);
    assert.match(invalid.stderr, /compact must/);
    assert.equal(readFileSync(join(root, 'once'), 'utf8'), '1');
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('run labels compacted streams only when shorter; byte limits retain existing incomplete delivery', async () => {
  const root = mkdtempSync(join(tmpdir(), 'julius-compaction-run-'));
  try {
    const economy = new Economy(root);
    const line = 'ERROR src/worker.ts:91 limit=17; do NOT retry\n';
    const script = `process.stdout.write(${JSON.stringify(line)}.repeat(1000)); process.stderr.write(${JSON.stringify('warning retained\n')}); process.exitCode = 3`;
    const result = await economy.run([process.execPath, '-e', script], { budget: 1200, compact: 'log' });
    const envelope = JSON.parse(result.text);
    assert.equal(result.status, 3);
    assert.equal(envelope.compaction, 'log');
    assert.ok(envelope.stdout.includes(line));
    assert.ok(envelope.stdout.includes('999 additional times'));
    assert.ok(envelope.stderr.includes('warning retained'));
    assert.ok(economyTokens(result.text) <= 1200);
    assert.equal((await economy.read(result.stdoutHandle, { budget: null, raw: true })).text, line.repeat(1000));
    const limited = await economy.run([process.execPath, '-e', script], { budget: 500, compact: 'log', maxBytes: 5000 });
    assert.equal(limited.complete, false);
    assert.equal(JSON.parse(limited.text).compaction, undefined);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
