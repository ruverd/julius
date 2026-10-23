import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { Session } from 'node:inspector';
import fs from 'node:fs';
import { syncBuiltinESMExports } from 'node:module';
import childProcess from 'node:child_process';

const here = dirname(fileURLToPath(import.meta.url));
const sha = text => createHash('sha256').update(text).digest('hex');
function treeHash(root, subtree) {
  const files = [];
  const walk = dir => { for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name); if (entry.isDirectory()) walk(path); else files.push(path);
  } };
  walk(join(root, subtree));
  return sha(JSON.stringify(files.sort().map(path => [relative(root, path).replaceAll('\\', '/'), sha(readFileSync(path))])));
}

async function worker(product, root) {
  let indexWrites = 0;
  let gitSpawns = 0;
  const originalWrite = fs.writeFileSync;
  const originalSpawn = childProcess.spawnSync;
  childProcess.spawnSync = function (command, ...args) {
    if (command === 'git') gitSpawns++;
    return originalSpawn.call(this, command, ...args);
  };
  fs.writeFileSync = function (path, ...args) {
    if (typeof path === 'string' && /(?:^|[/\\])wiring\.json\.\d+\.tmp$/.test(path)) indexWrites++;
    return originalWrite.call(this, path, ...args);
  };
  syncBuiltinESMExports();
  const { realNativeRequire, setNativeRequireForTest } = await import(pathToFileURL(join(product, 'dist/graph/native.js')).href);
  const nativeLoads = [];
  setNativeRequireForTest(id => {
    const start = performance.now();
    try { return realNativeRequire(id); }
    finally { nativeLoads.push({ module: id, elapsedMs: performance.now() - start }); }
  });
  const { runInvestigation } = await import(pathToFileURL(join(product, 'dist/investigation/index.js')).href);
  const args = { recipe: 'change-impact', paths: ['core.ts'], depth: 1 };
  const session = new Session(); session.connect();
  const post = method => new Promise((done, reject) => session.post(method, (error, value) => error ? reject(error) : done(value)));
  await post('Profiler.enable');
  await post('Profiler.start');
  const phases = [];
  const measured = async phase => {
    const writesBefore = indexWrites;
    const gitBefore = gitSpawns;
    const nativeBefore = nativeLoads.length;
    const start = performance.now();
    const report = await runInvestigation(root, args);
    phases.push({ phase, elapsedMs: performance.now() - start, indexWrites: indexWrites - writesBefore, gitSpawns: gitSpawns - gitBefore,
      nativeLoads: nativeLoads.slice(nativeBefore), reused: report.reused, evidence: report.evidence.length,
      evidenceSha256: sha(JSON.stringify({ coverage: report.coverage, unknowns: report.unknowns, evidence: report.evidence })) });
    return report;
  };
  await measured('first');
  for (let i = 0; i < 10; i++) assert.equal((await measured('warm')).reused, true);
  writeFileSync(join(root, 'added.ts'), 'import { hello } from "./core"; export function newlyAddedCaller() { return hello(); }\n');
  const changed = await measured('after-edit');
  assert.equal(changed.reused, false);
  assert.ok(changed.evidence.some(item => item.name === 'newlyAddedCaller'));
  writeFileSync(join(root, 'added-again.ts'), 'import { hello } from "./core"; export function secondAddedCaller() { return hello(); }\n');
  const changedAgain = await measured('after-second-edit');
  assert.equal(changedAgain.reused, false);
  assert.ok(changedAgain.evidence.some(item => item.name === 'secondAddedCaller'));
  const { profile } = await post('Profiler.stop'); session.disconnect();
  fs.writeFileSync = originalWrite;
  childProcess.spawnSync = originalSpawn;
  syncBuiltinESMExports();
  setNativeRequireForTest(null);
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

if (process.argv[2] === '--build') {
  const { buildGraph } = await import(pathToFileURL(join(resolve(process.argv[3]), 'dist/graph/build.js')).href);
  await buildGraph(resolve(process.argv[4]));
} else if (process.argv[2] === '--worker') {
  console.log(JSON.stringify(await worker(resolve(process.argv[3]), resolve(process.argv[4]))));
} else {
  const before = resolve(process.argv[2] ?? '');
  const candidate = resolve(process.argv[3] ?? '');
  const output = process.argv[4];
  const prebuilt = process.argv.includes('--prebuilt');
  const repetitions = Number(process.argv.find(arg => arg.startsWith('--repetitions='))?.split('=')[1] ?? 1);
  assert.ok(Number.isSafeInteger(repetitions) && repetitions >= 1 && repetitions <= 20);
  if (!output) throw new Error('Usage: node scripts/experiments/index-profile.mjs <built-before> <built-candidate> <report.json> [--prebuilt] [--repetitions=3]');
  const products = [['before', before], ['candidate', candidate]];
  const inputs = Object.fromEntries(products.map(([arm, root]) => [arm, { version: JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')).version,
    lockSha256: sha(readFileSync(join(root, 'package-lock.json'))), sourceSha256: treeHash(root, 'src'), distSha256: treeHash(root, 'dist') }]));
  const workspace = mkdtempSync(join(tmpdir(), 'julius-index-profile-'));
  const files = { 'core.ts': 'export function hello() { return 1; }\n' };
  for (let i = 0; i < 100; i++) files[`module${i}.ts`] = 'import { hello } from "./core";\n' + Array.from({ length: 10 }, (_, j) => `export function caller${i}_${j}() { return hello(); }\n`).join('');
  const results = [];
  try {
    for (let repetition = 0; repetition < repetitions; repetition++) for (const [arm, product] of repetition % 2 ? [...products].reverse() : products) {
      const root = join(workspace, `${arm}-${repetition}`); const home = join(root, 'home'); mkdirSync(home, { recursive: true });
      for (const [name, source] of Object.entries(files)) writeFileSync(join(root, name), source);
      const guardLog = join(root, 'blocked.log'); writeFileSync(guardLog, '');
      const options = { cwd: root, encoding: 'utf8', timeout: 120000,
        env: { PATH: process.env.PATH, HOME: home, USERPROFILE: home, CI: '1', DO_NOT_TRACK: '1', NODE_OPTIONS: `--require=${join(here, 'offline-guard.cjs')}`, JULIUS_PROBE_GUARD_LOG: guardLog } };
      if (prebuilt) execFileSync(process.execPath, [fileURLToPath(import.meta.url), '--build', product, root], options);
      const text = execFileSync(process.execPath, [fileURLToPath(import.meta.url), '--worker', product, root], options);
      assert.equal(readFileSync(guardLog, 'utf8'), '');
      results.push({ arm, repetition, ...JSON.parse(text) });
    }
  } finally { rmSync(workspace, { recursive: true, force: true }); }
  for (const result of results) assert.deepEqual(results[0].phases.map(phase => phase.evidenceSha256), result.phases.map(phase => phase.evidenceSha256), 'Index optimization must preserve investigation evidence');
  for (const [arm, root] of products) {
    assert.equal(treeHash(root, 'src'), inputs[arm].sourceSha256, `${arm} sources changed`);
    assert.equal(treeHash(root, 'dist'), inputs[arm].distSha256, `${arm} compiled output changed`);
    assert.equal(sha(readFileSync(join(root, 'package-lock.json'))), inputs[arm].lockSha256, `${arm} lockfile changed`);
  }
  writeFileSync(resolve(output), JSON.stringify({ version: 1, harnessSha256: sha(readFileSync(fileURLToPath(import.meta.url))), engineSha256: Object.fromEntries([['before', before], ['candidate', candidate]].map(([arm, root]) => [arm, sha(readFileSync(join(root, 'dist/investigation/index.js')))])), fixtureSha256: sha(JSON.stringify(files)), files: 101, functions: 1001, node: process.version,
    providerUsage: null, prebuilt, repetitions, inputs, scope: 'Single-process investigation profile, synthetic TypeScript sources. Optional prebuilt indexes are created in separate processes before profiling. Arm order alternates across repetitions. One first request, ten identical warm requests, two sequential source additions per fresh worker. Native require durations are recorded per phase. V8 sampling profile; native frames can include blocking waits, not CPU-cycle measurements or exact phase attribution. Not a statistically controlled speed comparison. Both arms retain the inherited index engine. No model calls.', results }, null, 2) + '\n');
}
