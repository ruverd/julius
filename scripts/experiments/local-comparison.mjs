import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFileSync, spawn } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createInterface } from 'node:readline';
import { get_encoding } from 'tiktoken';
import { gzipSync } from 'node:zlib';

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, '../..');
const upstream = 'b1211efd3eef0efa121b93800e5dd8e547aead77';
const manifestPath = join(here, 'local-comparison-tasks.json');
const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
const hash = value => createHash('sha256').update(value).digest('hex');
const tokenizer = get_encoding('cl100k_base');
const tokens = value => tokenizer.encode(value, [], []).length;
const pad = value => String(value).padStart(3, '0');

export function decision(baseline, candidate, quality) {
  if (!quality) return 'reject-quality';
  if (baseline === null || candidate === null) return 'inconclusive';
  return candidate < baseline ? 'advance-offline-only' : 'reject-no-saving';
}
export function envelope(text) {
  try {
    const parsed = JSON.parse(text);
    if (/^sha256:[a-f0-9]{64}$/.test(parsed.handle) && Number.isSafeInteger(parsed.end)) return parsed;
  } catch { /* Ordinary text and investigation JSON are not recovery envelopes. */ }
  return null;
}
export function decoded(value) {
  return Buffer.from(value.content, value.format === 'base64' ? 'base64' : 'utf8');
}
export function expectedFacts(task, spec = manifest) {
  if (task.kind === 'complete') return Array.from({ length: spec.functions }, (_, i) => `BENCH_MARKER_${pad(i)}: retry_limit=${i === spec.target ? 7 : 3}`);
  if (task.kind === 'impact') return ['hello', ...Array.from({ length: task.expectedCallers }, (_, i) => `caller${pad(i)}`)];
  return task.expected;
}

function sources(language) {
  const extension = { typescript: 'ts', python: 'py', go: 'go' }[language];
  const core = { typescript: 'export function hello() { return 1; }\n', python: 'def hello():\n    return 1\n', go: 'package demo\nfunc hello() int { return 1 }\n' }[language];
  let catalog = language === 'go' ? 'package demo\n' : '';
  let calls = { typescript: 'import { hello } from "./core";\n', python: 'from core import hello\n', go: 'package demo\n' }[language];
  for (let i = 0; i < manifest.functions; i++) {
    const fact = `BENCH_MARKER_${pad(i)}: retry_limit=${i === manifest.target ? 7 : 3}`;
    catalog += { typescript: `export function entry${pad(i)}() { return "${fact}"; }\n`, python: `def entry${pad(i)}():\n    return "${fact}"\n`, go: `func entry${pad(i)}() string { return "${fact}" }\n` }[language];
  }
  for (let i = 0; i < manifest.callers; i++) calls += { typescript: `export function caller${pad(i)}() { return hello(); }\n`, python: `def caller${pad(i)}():\n    return hello()\n`, go: `func caller${pad(i)}() int { return hello() }\n` }[language];
  return { extension, files: { [`core.${extension}`]: core, [`catalog.${extension}`]: catalog, [`callers.${extension}`]: calls } };
}

class Client {
  constructor(binary, root, env, full) {
    this.events = []; this.pending = new Map(); this.sequence = 0; this.stderr = '';
    this.child = spawn(process.execPath, [binary, 'mcp', root, ...(full ? ['--full-tools'] : [])], { cwd: root, env, stdio: ['pipe', 'pipe', 'pipe'] });
    this.child.stderr.on('data', chunk => { this.stderr += chunk; });
    createInterface({ input: this.child.stdout }).on('line', line => {
      let message;
      try { message = JSON.parse(line); } catch { this.fail(new Error(`Non-JSON stdout: ${line}`)); return; }
      const pending = this.pending.get(message.id);
      if (!pending) { this.fail(new Error('Unexpected response')); return; }
      this.events.push({ direction: 'response', stage: pending.stage, wire: `${line}\n`, tokens: tokens(`${line}\n`) });
      this.pending.delete(message.id); clearTimeout(pending.timer);
      if (message.error) pending.reject(new Error(JSON.stringify(message.error))); else pending.resolve(message.result);
    });
    this.child.on('error', error => this.fail(error));
    this.child.on('exit', code => this.fail(new Error(`MCP exited ${code}: ${this.stderr}`)));
  }
  fail(error) { for (const p of this.pending.values()) { clearTimeout(p.timer); p.reject(error); } this.pending.clear(); }
  request(method, params, stage) {
    const id = ++this.sequence; const wire = `${JSON.stringify({ jsonrpc: '2.0', id, method, ...(params ? { params } : {}) })}\n`;
    this.events.push({ direction: 'request', stage, wire, tokens: tokens(wire) });
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`Timeout: ${method}`)); }, 30000);
      this.pending.set(id, { resolve, reject, timer, stage }); this.child.stdin.write(wire);
    });
  }
  async start() {
    await this.request('initialize', { protocolVersion: '2025-03-26', capabilities: {}, clientInfo: { name: 'offline-comparison', version: '1' } }, 'interface');
    const wire = `${JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' })}\n`;
    this.events.push({ direction: 'request', stage: 'interface', wire, tokens: tokens(wire) }); this.child.stdin.write(wire);
    this.tools = (await this.request('tools/list', undefined, 'interface')).tools;
  }
  async call(name, args, stage = 'operation') {
    const result = await this.request('tools/call', { name, arguments: args }, stage);
    const text = result.content.map(c => c.text ?? '').join('\n');
    if (result.isError) throw new Error(text);
    return text;
  }
  async close() {
    if (this.child.exitCode !== null) return;
    await new Promise(resolve => {
      const timer = setTimeout(() => this.child.kill('SIGKILL'), 2000);
      this.child.once('exit', () => { clearTimeout(timer); resolve(); }); this.child.stdin.end();
    });
  }
}

function isolatedEnv(home, guardLog) {
  mkdirSync(home, { recursive: true });
  // Upstream has no update-check opt-out. Seed its real cache, without patching source.
  for (const directory of ['.graft', '.trail', '.julius']) {
    mkdirSync(join(home, directory));
    writeFileSync(join(home, directory, 'update-check.json'), JSON.stringify({ latest: null, checkedAt: Date.now() }));
  }
  writeFileSync(guardLog, '');
  return { PATH: process.env.PATH, ...(process.env.SystemRoot ? { SystemRoot: process.env.SystemRoot } : {}), HOME: home, USERPROFILE: home,
    CI: '1', DO_NOT_TRACK: '1', GIT_CONFIG_GLOBAL: join(home, 'no-git-config'), GIT_CONFIG_NOSYSTEM: '1',
    NODE_OPTIONS: `--require=${join(here, 'offline-guard.cjs')}`, JULIUS_PROBE_GUARD_LOG: guardLog };
}

async function runArm(trailRoot, workspace, language, task, arm) {
  const folder = join(workspace, `${language}-${task.kind}-${arm}`); mkdirSync(folder);
  const root = join(folder, 'repo'); mkdirSync(root);
  const fixture = sources(language);
  for (const [name, text] of Object.entries(fixture.files)) writeFileSync(join(root, name), text);
  const guardLog = join(folder, 'blocked.log'); const env = isolatedEnv(join(folder, 'home'), guardLog);
  const binary = join(arm === 'trail' ? trailRoot : repo, 'dist/bin', arm === 'trail' ? 'trail.js' : 'julius.js');
  let client; let error = null; let evidence = ''; let recoveryCalls = 0; let byteIntegrity = null;
  let initialQuality = false; const facts = expectedFacts(task);
  try {
    execFileSync(process.execPath, [binary, 'build', root], { cwd: root, env, timeout: 60000, stdio: 'pipe' });
    client = new Client(binary, root, env, arm === 'julius-full'); await client.start();
    const compact = !['trail', 'julius-full'].includes(arm);
    const budget = arm === 'compact-400' ? 400 : arm === 'composition' ? 16000 : 1200;
    const discovered = new Set();
    async function call(operation, args, stage = 'operation') {
      if (!compact) {
        const tool = client.tools.find(t => t.name.endsWith(`_${operation}`));
        assert.ok(tool, `Missing operation ${operation}`); return client.call(tool.name, args, stage);
      }
      const name = operation.includes('.') ? operation : `julius_${operation}`;
      if (!discovered.has(name)) { await client.call('julius_discover', { operation: name }, 'discovery'); discovered.add(name); }
      return client.call('julius_call', { operation: name, args, budget }, stage);
    }
    let results;
    if (arm === 'composition') results = [await call('investigation.execute', { recipe: 'change-impact', paths: [`core.${fixture.extension}`], depth: 1 })];
    else if (task.kind === 'tiny') results = [await call('file_api', { file: `core.${fixture.extension}` })];
    else if (task.kind === 'impact') results = [await call('file_api', { file: `core.${fixture.extension}` }), await call('trace_calls', { symbol: 'hello', depth: 1 })];
    else results = [await call('find_all', { pattern: task.query, fixed: true })];
    initialQuality = facts.every(fact => results.join('\n').includes(fact));
    for (const text of results) {
      const first = envelope(text);
      if (!first) { evidence += text + '\n'; continue; }
      if (task.kind === 'selective' && initialQuality) { evidence += decoded(first).toString('utf8') + '\n'; continue; }
      if (task.kind === 'selective' && !initialQuality) {
        const recovered = await call('context.read', { handle: first.handle, search: task.recoveryHint }, 'recovery'); recoveryCalls++;
        evidence += recovered + '\n';
      } else {
        const parts = [decoded(first)]; let end = first.end;
        while (end < first.totalBytes) {
          assert.ok(recoveryCalls < 300, 'Recovery call limit');
          const next = envelope(await call('context.read', { handle: first.handle, start: end }, 'recovery')); recoveryCalls++;
          assert.ok(next && next.start === end && next.end > end, 'Recovery must advance contiguously');
          parts.push(decoded(next)); end = next.end;
        }
        const bytes = Buffer.concat(parts);
        assert.equal(hash(bytes), first.handle.slice(7), 'Recovery byte integrity'); byteIntegrity = true;
        evidence += bytes.toString('utf8') + '\n';
      }
    }
  } catch (failure) { error = String(failure.message ?? failure).replaceAll(folder, '<trial>'); }
  finally { if (client) await client.close(); }
  const blocked = readFileSync(guardLog, 'utf8').trim().split('\n').filter(Boolean);
  if (blocked.length) error = `Offline guard triggered: ${blocked.join(', ')}`;
  const events = client?.events ?? []; const stageTokens = {};
  for (const event of events) stageTokens[event.stage] = (stageTokens[event.stage] ?? 0) + event.tokens;
  const missingFacts = facts.filter(fact => !evidence.includes(fact));
  return { language, task: task.kind, arm, quality: error === null && missingFacts.length === 0, initialQuality, missingFacts, error,
    byteIntegrity, recoveryCalls, stageTokens, totalTokens: events.length ? events.reduce((sum, e) => sum + e.tokens, 0) : null,
    calls: events.filter(e => e.direction === 'request' && e.stage !== 'interface').length, blockedOperations: blocked, events };
}

function verifyUpstream(trailRoot) {
  const entries = execFileSync('git', ['ls-tree', '-r', '--format=%(objectname) %(path)', upstream], { cwd: repo, encoding: 'utf8' }).trim().split('\n');
  for (const entry of entries) {
    const [expected, ...parts] = entry.split(' '); const path = parts.join(' '); const bytes = readFileSync(join(trailRoot, path));
    const actual = createHash('sha1').update(`blob ${bytes.length}\0`).update(bytes).digest('hex');
    assert.equal(actual, expected, `Upstream source changed: ${path}`);
  }
  return { commit: upstream, verifiedSourceFiles: entries.length, lockSha256: hash(readFileSync(join(trailRoot, 'package-lock.json'))) };
}

export async function runComparison(trailRoot, output) {
  const provenance = verifyUpstream(trailRoot);
  assert.ok(existsSync(join(trailRoot, 'dist/bin/trail.js')), 'Build the pinned upstream first');
  const workspace = mkdtempSync(join(tmpdir(), 'julius-comparison-')); const runs = [];
  try {
    for (const language of manifest.languages) for (const task of manifest.tasks) {
      const arms = ['trail', 'julius-full', ...manifest.budgets.map(n => `compact-${n}`), ...(task.kind === 'impact' ? ['composition'] : [])];
      // Alternate order to avoid always assigning warm OS caches to the candidate.
      if (runs.length % 2) arms.reverse();
      for (const arm of arms) { process.stderr.write(`${language}/${task.kind}/${arm}\n`); runs.push(await runArm(trailRoot, workspace, language, task, arm)); }
    }
  } finally { rmSync(workspace, { recursive: true, force: true }); }
  const traces = runs.map(({ language, task, arm, events }) => ({ language, task, arm, events }));
  const results = runs.map(({ events, ...run }) => {
    const baseline = runs.find(r => r.language === run.language && r.task === run.task && r.arm === 'trail');
    const full = runs.find(r => r.language === run.language && r.task === run.task && r.arm === 'julius-full');
    const savedTokens = baseline.totalTokens === null || run.totalTokens === null ? null : baseline.totalTokens - run.totalTokens;
    const work = r => r.totalTokens === null ? null : r.totalTokens - (r.stageTokens.interface ?? 0);
    return { ...run, savedTokensVsTrail: savedTokens, savingPercentVsTrail: savedTokens === null ? null : 100 * savedTokens / baseline.totalTokens,
      tokensExcludingInterface: work(run), workSavedVsFull: work(full) === null || work(run) === null ? null : work(full) - work(run),
      decision: decision(baseline.totalTokens, run.totalTokens, baseline.quality && run.quality) };
  });
  const report = { version: 1, upstream: provenance, julius: { commit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim(), lockSha256: hash(readFileSync(join(repo, 'package-lock.json'))) },
    node: process.version, encoding: 'cl100k_base', manifestSha256: hash(readFileSync(manifestPath)), harnessSha256: hash(readFileSync(fileURLToPath(import.meta.url))),
    sources: Object.fromEntries(manifest.languages.map(language => [language, hash(JSON.stringify(sources(language).files))])),
    providerUsage: null, providerCost: null, codingAccuracy: null,
    scope: 'Real CLI/MCP executables; synthetic evidence tasks; one run per arm; scripted calls and oracle quality checks. Exact NDJSON messages counted once, not provider prompt replay, model reasoning or host framing. Structural index preparation excluded. No paid/model calls.', results };
  mkdirSync(dirname(output), { recursive: true }); writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
  writeFileSync(output.replace(/\.json$/, '.traces.json.gz'), gzipSync(JSON.stringify(traces) + '\n'));
  return report;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const trailRoot = process.argv[2]; const output = process.argv[3];
  if (!trailRoot || !output) throw new Error('Usage: node scripts/experiments/local-comparison.mjs <built-upstream-directory> <report.json>');
  const report = await runComparison(resolve(trailRoot), resolve(output));
  console.log(JSON.stringify(report.results.map(({ language, task, arm, totalTokens, quality, recoveryCalls, workSavedVsFull }) => ({ language, task, arm, totalTokens, quality, recoveryCalls, workSavedVsFull })), null, 2));
}
