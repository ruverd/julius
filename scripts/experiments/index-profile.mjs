import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { Session } from 'node:inspector';

const here = dirname(fileURLToPath(import.meta.url));
const sha = text => createHash('sha256').update(text).digest('hex');

async function worker(product, root) {
  const { runInvestigation } = await import(pathToFileURL(join(product, 'dist/investigation/index.js')).href);
  const args = { recipe: 'change-impact', paths: ['core.ts'], depth: 1 };
  const session = new Session(); session.connect();
  const post = method => new Promise((done, reject) => session.post(method, (error, value) => error ? reject(error) : done(value)));
  await post('Profiler.enable');
  await post('Profiler.start');
  const phases = [];
  const measured = async phase => {
    const start = performance.now();
    const report = await runInvestigation(root, args);
    phases.push({ phase, elapsedMs: performance.now() - start, reused: report.reused, evidence: report.evidence.length, evidenceSha256: sha(JSON.stringify({ coverage: report.coverage, unknowns: report.unknowns, evidence: report.evidence })) });
    return report;
  };
  await measured('first');
  for (let i = 0; i < 10; i++) assert.equal((await measured('warm')).reused, true);
  writeFileSync(join(root, 'added.ts'), 'import { hello } from "./core"; export function newlyAddedCaller() { return hello(); }\n');
  const changed = await measured('after-edit');
  assert.equal(changed.reused, false);
  assert.ok(changed.evidence.some(item => item.name === 'newlyAddedCaller'));
  const { profile } = await post('Profiler.stop'); session.disconnect();
  const nodes = new Map(profile.nodes.map(node => [node.id, node.callFrame]));
  const buckets = new Map();
  profile.samples.forEach((id, index) => {
    const frame = nodes.get(id);
    let url = frame.url || '<native>';
    if (url.startsWith('file:')) {
      const path = fileURLToPath(url);
      const local = relative(realpathSync(product), path);
      url = !local.startsWith('..') ? local : path.includes('/node_modules/') ? 'node_modules/' + path.split('/node_modules/').pop() : '<external>/' + path.split('/').slice(-2).join('/');
    }
    const label = `${url}:${frame.lineNumber + 1} ${frame.functionName || '<anonymous>'}`;
    buckets.set(label, (buckets.get(label) ?? 0) + profile.timeDeltas[index]);
  });
  return { phases, sampledTimeMs: [...buckets].sort((a, b) => b[1] - a[1]).slice(0, 15).map(([frame, us]) => ({ frame, ms: us / 1000 })) };
}

if (process.argv[2] === '--worker') {
  console.log(JSON.stringify(await worker(resolve(process.argv[3]), resolve(process.argv[4]))));
} else {
  const before = resolve(process.argv[2] ?? '');
  const candidate = resolve(process.argv[3] ?? '');
  const output = process.argv[4];
  if (!output) throw new Error('Usage: node scripts/experiments/index-profile.mjs <built-before> <built-candidate> <report.json>');
  const workspace = mkdtempSync(join(tmpdir(), 'julius-index-profile-'));
  const files = { 'core.ts': 'export function hello() { return 1; }\n' };
  for (let i = 0; i < 100; i++) files[`module${i}.ts`] = 'import { hello } from "./core";\n' + Array.from({ length: 10 }, (_, j) => `export function caller${i}_${j}() { return hello(); }\n`).join('');
  const results = [];
  try {
    for (const [arm, product] of [['before', before], ['candidate', candidate]]) {
      const root = join(workspace, arm); const home = join(root, 'home'); mkdirSync(home, { recursive: true });
      for (const [name, source] of Object.entries(files)) writeFileSync(join(root, name), source);
      const guardLog = join(root, 'blocked.log'); writeFileSync(guardLog, '');
      const text = execFileSync(process.execPath, [fileURLToPath(import.meta.url), '--worker', product, root], { cwd: root, encoding: 'utf8', timeout: 120000,
        env: { PATH: process.env.PATH, HOME: home, USERPROFILE: home, CI: '1', DO_NOT_TRACK: '1', NODE_OPTIONS: `--require=${join(here, 'offline-guard.cjs')}`, JULIUS_PROBE_GUARD_LOG: guardLog } });
      assert.equal(readFileSync(guardLog, 'utf8'), '');
      results.push({ arm, ...JSON.parse(text) });
    }
  } finally { rmSync(workspace, { recursive: true, force: true }); }
  assert.deepEqual(results[0].phases.map(phase => phase.evidenceSha256), results[1].phases.map(phase => phase.evidenceSha256), 'Index optimization must preserve investigation evidence');
  writeFileSync(resolve(output), JSON.stringify({ version: 1, harnessSha256: sha(readFileSync(fileURLToPath(import.meta.url))), engineSha256: Object.fromEntries([['before', before], ['candidate', candidate]].map(([arm, root]) => [arm, sha(readFileSync(join(root, 'dist/investigation/index.js')))])), fixtureSha256: sha(JSON.stringify(files)), files: 101, functions: 1001, node: process.version,
    providerUsage: null, scope: 'Single-process investigation profile, synthetic TypeScript sources. One first request, ten identical warm requests, one source addition. V8 sampling profile; native frames can include blocking waits, not CPU-cycle measurements or exact phase attribution. Not a statistically controlled speed comparison. Both arms retain the inherited index engine. No model calls.', results }, null, 2) + '\n');
}
