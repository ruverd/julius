import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
const cli = resolve('src/cli.ts');
test('CLI capture/read/stats and run preserve bytes, status and isolated local accounting', () => {
  const root = mkdtempSync(join(tmpdir(), 'economy-cli-'));
  const env = { ...process.env, HOME: root, USERPROFILE: root, XDG_CONFIG_HOME: join(root, '.config') };
  const run = (args: string[], input?: Buffer | string) => spawnSync(process.execPath, ['--import', 'tsx', cli, ...args], { env, input });
  try {
    const input = Buffer.from('🙂\r\n'.repeat(500));
    const capture = run(['capture', '--repo', root, '--budget', '180'], input);
    assert.equal(capture.status, 0, capture.stderr.toString());
    const envelope = JSON.parse(capture.stdout.toString());
    const read = run(['read', envelope.handle, '--repo', root, '--raw']);
    assert.equal(read.status, 0, read.stderr.toString());
    assert.deepEqual(read.stdout, input);
    const stats = run(['economy', 'stats', '--repo', root]);
    assert.equal(stats.status, 0, stats.stderr.toString());
    assert.ok(JSON.parse(stats.stdout.toString()).savedTokens < 0);
    const command = run(['run', '--repo', root, '--budget', '300', '--', process.execPath, '-e', 'require("fs").appendFileSync("once", "1"); process.exit(9)']);
    assert.equal(command.status, 9, command.stderr.toString());
    assert.match(command.stdout.toString(), /"status":9/);
    assert.equal(readFileSync(join(root, 'once'), 'utf8'), '1');
    const signalArgs = ['-e', 'process.kill(process.pid, "SIGTERM")'];
    const directSignal = spawnSync(process.execPath, signalArgs, { env });
    assert.ifError(directSignal.error);
    const signal = run(['run', '--repo', root, '--budget', '300', '--', process.execPath, ...signalArgs]);
    assert.equal(signal.signal, directSignal.signal);
    assert.equal(signal.status, directSignal.status);
    const signalEnvelope = JSON.parse(signal.stdout.toString());
    assert.equal(signalEnvelope.signal, directSignal.signal);
    assert.equal(signalEnvelope.status, directSignal.status);
    const success = run(['run', '--repo', root, '--budget', '300', '--', process.execPath, '-e', 'process.stdout.write("passing output".repeat(1000))']);
    assert.equal(success.status, 0);
    assert.match(success.stdout.toString(), /"status":0/);
    const invalid = run(['capture', '--repo', root, '--budget', '0'], input);
    assert.equal(invalid.status, 1); assert.match(invalid.stderr.toString(), /budget/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('independent processes capture concurrently and the ledger includes every delivery', async () => {
  const root = mkdtempSync(join(tmpdir(), 'economy-concurrent-'));
  const env = { ...process.env, HOME: root, USERPROFILE: root, XDG_CONFIG_HOME: join(root, '.config') };
  const { spawn } = await import('node:child_process');
  const { Economy, economyTokens } = await import('../src/index.js');
  const input = 'same output\r\n'.repeat(1000);
  try {
    const texts = await Promise.all(Array.from({length: 6}, () => new Promise<string>((resolveRun, reject) => {
      const child = spawn(process.execPath, ['--import', 'tsx', cli, 'capture', '--repo', root, '--budget', '180'], {env});
      let stdout = ''; let stderr = '';
      child.stdout.on('data', chunk => stdout += chunk); child.stderr.on('data', chunk => stderr += chunk);
      child.on('error', reject); child.on('close', code => code === 0 ? resolveRun(stdout) : reject(new Error(stderr)));
      child.stdin.end(input);
    })));
    const stats = await new Economy(root).stats();
    assert.equal(new Set(texts).size, 1);
    assert.equal(stats.events, 6); assert.equal(stats.rawTokens, 6 * economyTokens(input));
    assert.equal(stats.deliveredTokens, texts.reduce((sum, text) => sum + economyTokens(text), 0));
  } finally { rmSync(root, {recursive:true, force:true}); }
});

test('explicit economy clear invalidates local handles and preserves shared learnings', () => {
  const root = mkdtempSync(join(tmpdir(), 'economy-clear-'));
  const env = { ...process.env, HOME: root, USERPROFILE: root, XDG_CONFIG_HOME: join(root, '.config') };
  const run = (args: string[], input?: string) => spawnSync(process.execPath, ['--import', 'tsx', cli, ...args], {env, input});
  try {
    const capture = run(['capture', '--repo', root, '--budget', '180'], 'payload\n'.repeat(500));
    assert.equal(capture.status, 0, capture.stderr.toString());
    const {handle} = JSON.parse(capture.stdout.toString());
    mkdirSync(join(root, '.julius/learnings'));
    writeFileSync(join(root, '.julius/learnings/team.md'), 'shared context');
    const refused = run(['economy', 'clear', '--repo', root]);
    assert.notEqual(refused.status, 0);
    assert.equal(run(['read', handle, '--repo', root, '--raw']).status, 0);
    const clear = run(['economy', 'clear', '--all', '--repo', root]);
    assert.equal(clear.status, 0, clear.stderr.toString());
    assert.equal(readFileSync(join(root, '.julius/learnings/team.md'), 'utf8'), 'shared context');
    const missing = run(['read', handle, '--repo', root, '--raw']);
    assert.equal(missing.status, 1);
    assert.match(missing.stderr.toString(), /missing|expired/);
    assert.equal(JSON.parse(run(['economy', 'stats', '--repo', root]).stdout.toString()).events, 0);
  } finally { rmSync(root, {recursive: true, force: true}); }
});
