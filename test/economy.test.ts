import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync, type PathLike } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import * as api from '../src/index.js';

test('public capture and read recover exact Unicode/CRLF, budget the whole delivery, and ledger retrieval', async () => {
  assert.equal(typeof api.Economy, 'function');
  const root = mkdtempSync(join(tmpdir(), 'economy-'));
  try {
    const economy = new api.Economy(root);
    const original = 'α🙂\r\n<|endoftext|> '.repeat(300);
    const captured = await economy.capture(original, { budget: 180 });
    assert.ok(captured.handle);
    assert.ok(api.economyTokens(captured.text) <= 180);
    const read = await economy.read(captured.handle!, { budget: 20000 });
    assert.equal(read.bytes.toString('utf8'), original);
    const stats = await economy.stats();
    assert.equal(stats.rawTokens, api.economyTokens(original));
    assert.equal(stats.deliveredTokens, api.economyTokens(captured.text) + api.economyTokens(read.text));
    assert.ok(stats.savedTokens < 0);
    const short = await economy.capture('ok', { budget: 10 });
    assert.equal(short.text, 'ok');
    assert.equal(short.handle, null);
    await assert.rejects(economy.capture(original, { budget: 1 }), /minimum|budget/i);
    await assert.rejects(economy.capture(original, { budget: NaN }), /budget/i);
    await assert.rejects(economy.read('../outside', { budget: 200 }), /handle/i);
    await assert.rejects(economy.read('sha256:' + '0'.repeat(64), { budget: 200 }), /missing|expired/i);
    writeFileSync(join(root, '.julius/economy/objects', captured.handle!.slice(7)), 'corrupt');
    await assert.rejects(economy.read(captured.handle!, { budget: 200 }), /corrupt/i);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('run executes argv once, preserves failures/signals, and budgets the combined response', async () => {
  const root = mkdtempSync(join(tmpdir(), 'economy-run-'));
  try {
    const economy = new api.Economy(root);
    assert.equal(typeof economy.run, 'function');
    const arg = '; echo no $(touch nope)';
    const result = await economy.run([process.execPath, '-e', 'process.stdout.write(process.argv[1]); process.stderr.write("failure ".repeat(1000)); process.exitCode=7', arg], { budget: 300 });
    assert.equal(result.status, 7);
    assert.equal(result.signal, null);
    assert.equal(result.complete, true);
    assert.ok(api.economyTokens(result.text) <= 300);
    assert.match(result.text, /"status":7/);
    assert.equal((await economy.read(result.stdoutHandle, { budget: 100, raw: true })).bytes.toString(), arg);
    assert.equal((await economy.read(result.stderrHandle, { budget: 100, raw: true })).bytes.toString(), 'failure '.repeat(1000));
    const stats = await economy.stats();
    assert.equal(stats.rawTokens, api.economyTokens(arg) + api.economyTokens('failure '.repeat(1000)));
    assert.equal(stats.deliveredTokens, api.economyTokens(result.text) + stats.rawTokens);
    const empty = await economy.run([process.execPath, '-e', 'process.exit(4)'], { budget: 300 });
    assert.equal(empty.status, 4); assert.match(empty.text, /"status":4/);
    const signal = await economy.run([process.execPath, '-e', 'process.kill(process.pid,"SIGTERM")'], { budget: 300 });
    assert.equal(signal.signal, 'SIGTERM'); assert.equal(signal.status, null);
    const limit = await economy.run([process.execPath, '-e', 'process.stdout.write("x".repeat(10000))'], { budget: 300, maxBytes: 100 });
    assert.equal(limit.complete, false); assert.equal(limit.limit, 'bytes');
    assert.equal((await economy.read(limit.stdoutHandle, { budget: 100, raw: true })).bytes.length, 100);
    await assert.rejects(economy.run([process.execPath, '-e', 'require("fs").writeFileSync("should-not-run", "x")'], { budget: 1 }), /budget|minimum/i);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('binary, byte slices, search, repeated captures and bounded diagnostics are honest', async () => {
  const root = mkdtempSync(join(tmpdir(), 'economy-bytes-'));
  try {
    const economy = new api.Economy(root);
    const binary = Buffer.from([0xff, 0, 0xfe, 13, 10]);
    const result = await economy.capture(binary, { budget: 180 });
    assert.ok(result.handle);
    assert.deepEqual((await economy.read(result.handle!, { budget: 1, raw: true })).bytes, binary);
    const input = 'single long line 你好'.repeat(1000);
    const first = await economy.capture(input, { budget: 180 });
    const second = await new api.Economy(root).capture(input, { budget: 180 });
    assert.equal(first.handle, second.handle); assert.equal(first.text, second.text);
    const part = await economy.read(first.handle!, { start: 3, end: 41, budget: 180 });
    assert.deepEqual(part.bytes, Buffer.from(input).subarray(3, 41));
    assert.equal(part.omittedBytes, Buffer.byteLength(input) - 38);
    const found = await economy.read(first.handle!, { search: '你好', end: 100, budget: 180 });
    assert.equal(JSON.parse(found.text).start, Buffer.from(input).indexOf(Buffer.from('你好')));
    for (const options of [{start: -1}, {end: 1000000}, {search: ''}, {search: 'not-here'}])
      await assert.rejects(economy.read(first.handle!, { budget: 180, ...options }));
    for (const budget of [0, -1, Infinity, 1.5, 1000001]) await assert.rejects(economy.capture('text', {budget}), /budget/);
    assert.equal((await economy.capture('', {budget: 1})).text, '');
    const stats = await economy.stats();
    assert.equal(stats.rawTokens, api.economyTokens(binary.toString('base64')) + 2 * api.economyTokens(input));
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('store containment, capture limits, timeout and spawn errors are explicit', async () => {
  const { symlinkSync, mkdirSync, existsSync } = await import('node:fs');
  const root = mkdtempSync(join(tmpdir(), 'economy-safe-'));
  const outside = mkdtempSync(join(tmpdir(), 'economy-outside-'));
  try {
    const economy = new api.Economy(root);
    await assert.rejects(economy.capture(Buffer.alloc(api.ECONOMY_MAX_BYTES + 1), {budget: 180}), /limit/);
    assert.equal(existsSync(join(root, '.julius')), false);
    mkdirSync(join(root, '.julius')); symlinkSync(outside, join(root, '.julius/economy'), 'dir');
    await assert.rejects(economy.capture('x', {budget: 10}), /Unsafe/);
    rmSync(join(root, '.julius/economy'));
    const timeout = await economy.run([process.execPath, '-e', 'setInterval(()=>{},10000)'], {budget: 300, timeoutMs: 20});
    assert.equal(timeout.complete, false); assert.equal(timeout.limit, 'timeout'); assert.equal(timeout.signal, 'SIGKILL');
    await assert.rejects(economy.run(['/this-command-does-not-exist'], {budget: 300}), /ENOENT/);
    for (const options of [{maxBytes: 0}, {maxBytes: api.ECONOMY_MAX_BYTES + 1}, {timeoutMs: 0}])
      await assert.rejects(economy.run([process.execPath], {budget: 300, ...options}));
    await assert.rejects(economy.run([], {budget: 300}), /argv/);
    await assert.rejects(economy.run(['x\0y'], {budget: 300}), /NUL/);
    const result = await economy.capture('output '.repeat(500), {budget: 180});
    const object = join(root, '.julius/economy/objects', result.handle!.slice(7));
    rmSync(object); writeFileSync(join(outside, 'secret'), 'secret'); symlinkSync(join(outside,'secret'), object);
    await assert.rejects(economy.read(result.handle!, {budget: 180}), /Unsafe/);
  } finally { rmSync(root, {recursive:true, force:true}); rmSync(outside, {recursive:true, force:true}); }
});

test('ordinary verbose commands above 64 KiB complete once with unchanged status and exact recovery', async () => {
  const { readFileSync } = await import('node:fs');
  const root = mkdtempSync(join(tmpdir(), 'economy-large-'));
  try {
    const economy = new api.Economy(root);
    const output = 'passing test: all assertions match\r\n'.repeat(8000);
    const script = 'require("fs").appendFileSync("executions", "1"); process.stdout.write("passing test: all assertions match\\r\\n".repeat(8000))';
    const result = await economy.run([process.execPath, '-e', script], {budget: 512});
    assert.equal(result.complete, true);
    assert.equal(result.status, 0);
    assert.equal(result.signal, null);
    assert.equal(readFileSync(join(root, 'executions'), 'utf8'), '1');
    assert.equal((await economy.read(result.stdoutHandle, {budget: 512, raw: true})).bytes.toString(), output);
    assert.equal((await economy.stats()).rawTokens, api.economyTokens(output));
    const captured = await economy.capture(output, {budget: 512});
    assert.equal((await economy.read(captured.handle!, {budget: 512, raw: true})).bytes.toString(), output);
    assert.ok(api.ECONOMY_MAX_BYTES >= 8 * 1024 * 1024);
  } finally { rmSync(root, {recursive: true, force: true}); }
});

test('command diagnostics surface failures beyond the prefix with nearby context and tail', async () => {
  const root = mkdtempSync(join(tmpdir(), 'economy-diagnostics-'));
  try {
    const economy = new api.Economy(root);
    const script = 'process.stdout.write("setup complete\\n" + "noise step passed\\n".repeat(500) + "suite: recovery contract\\nERROR unique-middle-defect\\nexpected intact bytes\\n" + "cleanup passed\\n".repeat(500) + "FINAL exit summary\\n"); process.exitCode=2';
    const result = await economy.run([process.execPath, '-e', script], {budget: 512});
    assert.equal(result.status, 2);
    assert.match(result.text, /unique-middle-defect/);
    assert.match(result.text, /recovery contract/);
    assert.match(result.text, /expected intact bytes/);
    assert.match(result.text, /FINAL exit summary/);
    assert.ok(api.economyTokens(result.text) <= 512);
    assert.match(result.text, /omitted/);
  } finally { rmSync(root, {recursive: true, force: true}); }
});

test('pathological 8 MiB payloads remain recoverable with unknown counts and no partial savings', async () => {
  const root = mkdtempSync(join(tmpdir(), 'economy-unknown-'));
  try {
    const economy = new api.Economy(root);
    const input = 'x'.repeat(8 * 1024 * 1024);
    const result = await economy.capture(input, {budget: 512});
    assert.ok(result.handle);
    assert.ok(api.economyTokens(result.text) <= 512);
    let stats = await economy.stats();
    assert.equal(stats.rawTokens, null);
    assert.equal(stats.savedTokens, null);
    assert.equal(stats.deliveredTokens, api.economyTokens(result.text));
    assert.equal(stats.rawUncountedEvents, 1);
    assert.equal(stats.uncountedEvents, 1);
    const read = await economy.read(result.handle!, {budget: 1, raw: true});
    assert.equal(read.bytes.toString(), input);
    stats = await economy.stats();
    assert.equal(stats.deliveredTokens, null);
    assert.equal(stats.deliveredUncountedEvents, 1);
    assert.equal(stats.uncountedEvents, 2);
    assert.equal(stats.accountedEvents, 0);
    assert.throws(() => api.economyTokens(input), /unavailable/);
    assert.throws(() => api.economyTokens(' '.repeat(8192)), /unavailable/);
    assert.throws(() => api.economyTokens('\n'.repeat(8192)), /unavailable/);
    const escapes = await economy.capture('\\'.repeat(8192), {budget: 512});
    assert.ok(api.economyTokens(escapes.text) <= 512);
    assert.equal((await economy.read(escapes.handle!, {budget: 512, raw: true})).bytes.toString(), '\\'.repeat(8192));
    const run = await economy.run([process.execPath, '-e', 'process.stdout.write("x".repeat(8192))'], {budget: 512});
    assert.equal(run.complete, true);
    assert.ok(api.economyTokens(run.text) <= 512);
    assert.equal((await economy.read(run.stdoutHandle, {budget: 512, raw: true})).bytes.length, 8192);
  } finally { rmSync(root, {recursive: true, force: true}); }
});

test('non-regular object files fail without blocking on a FIFO', {skip: process.platform === 'win32'}, async () => {
  const { spawnSync } = await import('node:child_process');
  const { mkdirSync } = await import('node:fs');
  const root = mkdtempSync(join(tmpdir(), 'economy-fifo-'));
  try {
    mkdirSync(join(root, '.julius/economy/objects'), {recursive: true});
    const handle = 'sha256:' + '0'.repeat(64);
    const fifo = spawnSync('mkfifo', [join(root, '.julius/economy/objects', handle.slice(7))]);
    assert.equal(fifo.status, 0);
    const probe = spawnSync(process.execPath, ['--import', 'tsx', '--input-type=module', '-e',
      `import {Economy} from './src/economy/index.ts'; try { await new Economy(process.argv[1]).read(process.argv[2], {budget: 180}); process.exitCode=2; } catch(error) { console.error(error.message); process.exitCode=1; }`, root, handle],
    {timeout: 3000, env: {...process.env, HOME: root, USERPROFILE: root, XDG_CONFIG_HOME: join(root, '.config')}});
    assert.equal(probe.error, undefined, 'Reading a FIFO must reject promptly instead of blocking');
    assert.equal(probe.status, 1);
    assert.match(probe.stderr.toString(), /Unsafe economy store file/);
  } finally { rmSync(root, {recursive: true, force: true}); }
});

test('ledger publication failure leaves recoverable bytes and retry accounts only one successful capture', async (t) => {
  const fs = await import('node:fs');
  const { syncBuiltinESMExports } = await import('node:module');
  const { createHash } = await import('node:crypto');
  const root = mkdtempSync(join(tmpdir(), 'economy-publication-'));
  const input = 'preserve this exact payload\r\n'.repeat(500);
  const hash = createHash('sha256').update(input).digest('hex');
  const object = join(root, '.julius/economy/objects', hash);
  const events = join(root, '.julius/economy/events');
  const rename = fs.default.renameSync;
  const fault = t.mock.method(fs.default, 'renameSync', (from: PathLike, to: PathLike) => {
    if (String(to).startsWith(events) && String(to).endsWith('.json')) {
      assert.equal(fs.readFileSync(object, 'utf8'), input, 'payload is published before the ledger publication failure');
      throw Object.assign(new Error('injected ledger publication EIO'), {code: 'EIO'});
    }
    return rename(from, to);
  });
  syncBuiltinESMExports();
  try {
    const economy = new api.Economy(root);
    await assert.rejects(economy.capture(input, {budget: 180}), /injected ledger publication EIO/);
    assert.deepEqual(fs.readdirSync(events).filter(name => name.endsWith('.json')), []);
    assert.equal((await economy.stats()).events, 0);
    fault.mock.restore(); syncBuiltinESMExports();
    const retry = await economy.capture(input, {budget: 180});
    assert.equal(retry.handle, `sha256:${hash}`);
    assert.deepEqual(fs.readdirSync(join(root, '.julius/economy/objects')), [hash]);
    const stats = await economy.stats();
    assert.equal(stats.events, 1);
    assert.equal(stats.rawTokens, api.economyTokens(input));
    assert.equal(stats.deliveredTokens, api.economyTokens(retry.text));
    assert.equal((await economy.read(retry.handle!, {budget: 1, raw: true})).bytes.toString(), input);
  } finally {
    fault.mock.restore(); syncBuiltinESMExports();
    rmSync(root, {recursive: true, force: true});
  }
});

test('command ledger failure rejects without repeating the executed side effect', async (t) => {
  const fs = await import('node:fs');
  const { syncBuiltinESMExports } = await import('node:module');
  const { createHash } = await import('node:crypto');
  const root = mkdtempSync(join(tmpdir(), 'economy-command-publication-'));
  const events = join(root, '.julius/economy/events');
  const rename = fs.default.renameSync;
  const fault = t.mock.method(fs.default, 'renameSync', (from: PathLike, to: PathLike) => {
    if (String(to).startsWith(events) && String(to).endsWith('.json')) throw new Error('injected command ledger failure');
    return rename(from, to);
  });
  syncBuiltinESMExports();
  try {
    const economy = new api.Economy(root);
    await assert.rejects(economy.run([process.execPath, '-e',
      'require("fs").appendFileSync("executions", "1"); process.stdout.write("exact stdout\\r\\n"); process.stderr.write("exact stderr\\n");'],
    {budget: 512}), /injected command ledger failure/);
    assert.equal(fs.readFileSync(join(root, 'executions'), 'utf8'), '1');
    for (const output of ['exact stdout\r\n', 'exact stderr\n']) {
      const hash = createHash('sha256').update(output).digest('hex');
      assert.equal(fs.readFileSync(join(root, '.julius/economy/objects', hash), 'utf8'), output);
    }
    fault.mock.restore(); syncBuiltinESMExports();
    const stats = await economy.stats();
    assert.equal(stats.events, 0);
    assert.equal(stats.rawTokens, 0);
    assert.equal(stats.deliveredTokens, 0);
    assert.equal(fs.readFileSync(join(root, 'executions'), 'utf8'), '1');
  } finally {
    fault.mock.restore(); syncBuiltinESMExports();
    rmSync(root, {recursive: true, force: true});
  }
});

test('capture refuses corrupt existing content without replacing it or recording success', async () => {
  const { readFileSync } = await import('node:fs');
  const root = mkdtempSync(join(tmpdir(), 'economy-corrupt-retry-'));
  try {
    const economy = new api.Economy(root);
    const input = 'same payload repeated\n'.repeat(500);
    const initial = await economy.capture(input, {budget: 180});
    const before = await economy.stats();
    const path = join(root, '.julius/economy/objects', initial.handle!.slice(7));
    writeFileSync(path, 'unexpected bytes');
    await assert.rejects(economy.capture(input, {budget: 180}), /Corrupt economy object/);
    assert.equal(readFileSync(path, 'utf8'), 'unexpected bytes');
    assert.deepEqual(await economy.stats(), before);
  } finally { rmSync(root, {recursive: true, force: true}); }
});

test('stats rejects a malformed committed ledger event instead of skipping it or returning partial totals', async () => {
  const root = mkdtempSync(join(tmpdir(), 'economy-corrupt-ledger-'));
  try {
    const economy = new api.Economy(root);
    await economy.capture('a valid prior delivery', {budget: 180});
    assert.equal((await economy.stats()).events, 1);
    const path = join(root, '.julius/economy/events', 'ffffffff-ffff-ffff-ffff-ffffffffffff.json');
    writeFileSync(path, JSON.stringify({rawTokens: -1, deliveredTokens: 4}));
    await assert.rejects(economy.stats(), /Corrupt economy ledger event/);
    rmSync(path);
    const restored = await economy.stats();
    assert.equal(restored.events, 1);
    assert.equal(restored.rawTokens, api.economyTokens('a valid prior delivery'));
    assert.equal(restored.deliveredTokens, restored.rawTokens);
  } finally { rmSync(root, {recursive: true, force: true}); }
});
