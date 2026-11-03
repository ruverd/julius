import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, symlinkSync, writeFileSync } from 'node:fs';
import { cpus, tmpdir, totalmem } from 'node:os';
import { dirname, join, relative, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { queries } from './cases.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, '../../..');
const work = resolve(process.argv[2] ?? mkdtempSync(join(tmpdir(), 'julius-rust-extractor-')));
const output = resolve(process.argv[3] ?? join(repo, 'docs/strategy/rust-extractor'));
const sha = x => createHash('sha256').update(x).digest('hex');
const json = (path, value) => { mkdirSync(dirname(path), { recursive: true }); writeFileSync(path, JSON.stringify(value, null, 2) + '\n'); };
function treeHash(root) {
  const rows = [];
  function visit(dir) { for (const e of readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    const path = join(dir, e.name);
    if (e.isDirectory()) visit(path); else if (e.isFile()) rows.push([relative(root, path), sha(readFileSync(path))]);
  } }
  visit(root); return sha(JSON.stringify(rows));
}
mkdirSync(work, { recursive: true });
assert.ok(!existsSync(join(work, 'baseline')), 'Use a fresh work directory');
const sourceHash = treeHash(join(repo, 'src'));
const baseline = join(work, 'baseline'); const candidate = join(work, 'candidate');
for (const path of ['src', 'viewer', 'package.json', 'package-lock.json', 'tsconfig.json', 'scripts/build-viewer.mjs']) {
  mkdirSync(dirname(join(baseline, path)), { recursive: true }); cpSync(join(repo, path), join(baseline, path), { recursive: true });
}
symlinkSync(join(repo, 'node_modules'), join(baseline, 'node_modules'));
console.error(`Work directory: ${work}\nBuilding isolated TypeScript snapshot`);
execFileSync('npm', ['run', 'build'], { cwd: baseline, stdio: ['ignore', 'pipe', 'pipe'] });
cpSync(baseline, candidate, { recursive: true, dereference: false });
const extractPath = join(candidate, 'dist/graph/extract.js');
const original = readFileSync(extractPath, 'utf8');
const needle = 'export function extractFile(rel, source, lang) {';
assert.equal(original.split(needle).length, 2);
writeFileSync(extractPath, `import { extractRust } from ${JSON.stringify(pathToFileURL(join(here, 'adapter.mjs')).href)};\n` + original.replace(needle,
  needle + '\n    if (lang === "typescript" || lang === "tsx") return extractRust(rel, source, lang, { contentHash, fileResidual, searchBody, clean });'));
const arms = { baseline, candidate };
const home = join(work, 'home'); mkdirSync(home, { recursive: true });
const guard = join(work, 'offline.log'); writeFileSync(guard, '');
const env = { PATH: process.env.PATH, HOME: home, USERPROFILE: home, CI: '1', DO_NOT_TRACK: '1',
  JULIUS_PROBE_GUARD_LOG: guard, JULIUS_RUST_ADDON: join(here, 'extractor.node'),
  NODE_OPTIONS: `--require=${join(here, '../offline-guard.cjs')} --require=${join(here, '../selective-index-resources.cjs')}` };
const specs = Object.keys(queries);
const report = { version: 1, date: new Date().toISOString(), work,
  revision: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim(),
  sourceSha256: sourceHash, lockSha256: sha(readFileSync(join(repo, 'package-lock.json'))),
  runtimeHashes: Object.fromEntries(Object.entries(arms).map(([arm, root]) => [arm, treeHash(join(root, 'dist'))])),
  rustSha256: sha(readFileSync(join(here, 'src/lib.rs'))), adapterSha256: sha(readFileSync(join(here, 'adapter.mjs'))),
  addonSha256: sha(readFileSync(join(here, 'extractor.node'))), cargoLockSha256: sha(readFileSync(join(here, 'Cargo.lock'))),
  harnessSha256: sha(readFileSync(fileURLToPath(import.meta.url))), workerSha256: sha(readFileSync(join(here, 'worker.mjs'))),
  node: process.version, platform: process.platform, cpu: cpus()[0].model, logicalCpus: cpus().length, memoryBytes: totalmem(),
  gate: { exactExtractionGraphIndexAndQueryParity: true, minRealFullBuildReduction: 0.2, maxIncrementalRegression: 0.1,
    maxWarmQueryRegression: 0.1, maxBuildPeakRSSRegression: 0.1,
    meaning: 'Local pilot gate for further hybrid development, not release approval or evidence for a full rewrite. Medians across four fresh workers per arm, rotated order.' },
  scope: 'Offline TS/TSX/JS structural extractor via synchronous in-process Node-API. Identical installed Tree-sitter core and grammar C sources. Rust returns compact definition tuples and unresolved edge tuples; existing TypeScript helpers materialize signatures/body text/hashes and residuals, resolve edges, build/search index and serve CLI/MCP. Other languages retain existing extractor. Complete indexing includes markdown cards. Every build phase uses a fresh process so peak RSS is phase-specific; caches remain on disk between full/unchanged/edit/add/delete. Native module still initialized by existing tier selection, so candidate retains that overhead. Build elapsedMs excludes imports/addon load; processElapsedMs includes them. Baseline never loads the Rust addon. Warm query and no-refresh CLI operate on identical saved graphs; no search-speed benefit is expected. Fresh process is not cold OS cache. One machine, uncontrolled load/cache/frequency, local development queries, no confidence intervals or agent-success evidence.',
  providerUsage: null, providerCost: null, agentCorrectness: null, corpora: [] };
json(join(output, 'plan.json'), { ...report, corpora: specs });
function run(product, corpus, mode, resultPath, id) {
  const start = performance.now();
  const result = JSON.parse(execFileSync(process.execPath, ['--expose-gc', join(here, 'worker.mjs'), product, corpus, mode, resultPath, id],
    { cwd: corpus, env, encoding: 'utf8', timeout: 240000, maxBuffer: 64 * 1024 * 1024 }));
  return { ...result, processElapsedMs: performance.now() - start };
}
async function mcp(product, corpus, query, round, arm) {
  const resourcePath = join(work, `mcp-${round}-${arm}.json`);
  const child = spawn(process.execPath, [join(product, 'dist/bin/julius.js'), 'mcp', corpus], {
    cwd: corpus, env: { ...env, JULIUS_SELECTIVE_RESOURCES: resourcePath }, stdio: ['pipe', 'pipe', 'pipe'],
  });
  let sequence = 0; let stderr = ''; const pending = new Map();
  child.stderr.on('data', chunk => { stderr += chunk; });
  const closed = new Promise(done => child.on('close', code => {
    for (const p of pending.values()) p.reject(new Error(`MCP exit ${code}: ${stderr}`)); pending.clear(); done(code);
  }));
  createInterface({ input: child.stdout }).on('line', line => {
    const response = JSON.parse(line); const p = pending.get(response.id);
    if (p) { pending.delete(response.id); response.error ? p.reject(new Error(JSON.stringify(response.error))) : p.resolve(response.result); }
  });
  function request(method, params) {
    const id = ++sequence;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { child.kill(); reject(new Error(`MCP timeout ${method}`)); }, 60000);
      pending.set(id, { resolve: x => { clearTimeout(timer); resolve(x); }, reject: e => { clearTimeout(timer); reject(e); } });
      child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
    });
  }
  const start = performance.now();
  try {
    await request('initialize', { protocolVersion: '2025-03-26', capabilities: {}, clientInfo: { name: 'rust-extraction-pilot', version: '1' } });
    child.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');
    await request('tools/call', { name: 'julius_discover', arguments: { operation: 'julius_find_code' } });
    const startupMs = performance.now() - start; const rows = [];
    for (let pass = 0; pass < 4; pass++) {
      const started = performance.now();
      const result = await request('tools/call', { name: 'julius_call', arguments: { operation: 'julius_find_code', args: { query, limit: 8 }, delivery: 'complete' } });
      assert.ok(!result.isError, JSON.stringify(result));
      rows.push({ pass, elapsedMs: performance.now() - started, hash: sha(result.content.map(c => c.text ?? '').join('\n')) });
    }
    return { startupMs, rows };
  } finally { child.stdin.end(); assert.equal(await closed, 0); }
}
for (const id of specs) {
  console.error(`Preparing ${id}`);
  const corpus = join(work, 'corpora', id); mkdirSync(corpus, { recursive: true });
  if (id === 'julius') cpSync(join(baseline, 'src'), join(corpus, 'src'), { recursive: true });
  else if (id === 'commander') {
    cpSync(join(repo, 'node_modules/commander/lib'), join(corpus, 'lib'), { recursive: true });
    cpSync(join(repo, 'node_modules/commander/index.js'), join(corpus, 'index.js'));
  } else for (const scope of ['a', 'b']) {
    const root = join(corpus, 'packages', scope); mkdirSync(join(root, 'src'), { recursive: true });
    json(join(root, 'package.json'), { name: `rust-pilot-${scope}`, version: '1.0.0' });
    writeFileSync(join(root, 'src/core.ts'), 'export class Base { run(payload: string) { return payload; } }\nexport function core(value: string) { return value; }\n');
    for (let i = 0; i < 500; i++) writeFileSync(join(root, `src/module${i}.ts`),
      `import { core, Base as Parent } from "./core";\nexport class Worker${i} extends Parent { run(payload: string) { return core(super.run(payload)); } }\n` +
      Array.from({ length: 10 }, (_, j) => `export function entry${scope}${i}_${j}(payload: string) { const worker = new Worker${i}(); const catalog = "rareNeedle${i * 10 + j} shared transport retry 🦀"; return worker.run(core(payload + catalog)); }\n`).join(''));
  }
  json(join(corpus, 'package.json'), { name: `rust-pilot-${id}`, version: '1.0.0', type: 'module' });
  const record = { id, corpusSha256: treeHash(corpus), extraction: {}, build: [], query: [], cli: [], mcp: [] };
  for (const [arm, product] of Object.entries(arms)) record.extraction[arm] = run(product, corpus, 'extract', join(work, `${id}-${arm}-extracted.json`), id);
  const baseResults = JSON.parse(readFileSync(join(work, `${id}-baseline-extracted.json`)));
  const candidateResults = JSON.parse(readFileSync(join(work, `${id}-candidate-extracted.json`)));
  assert.deepEqual(candidateResults, baseResults, `${id}: exact nodes and raw edges, including source bodies and hashes`);
  assert.ok(record.extraction.candidate.counters.files > 0, 'Rust path must execute');
  console.error(`${id}: ${record.extraction.baseline.cases} extraction cases match; benchmarking`);
  for (let round = 0; round < 4; round++) {
    const order = round % 2 ? Object.entries(arms).reverse() : Object.entries(arms);
    for (const [arm, product] of order) {
      console.error(`${id} round ${round + 1}/4 ${arm}`);
      const rows = [];
      for (const phase of ['full', 'unchanged', 'one-file-edit', 'addition', 'deletion']) {
        const result = run(product, corpus, 'build', phase, id);
        rows.push({ ...result.rows[0], processElapsedMs: result.processElapsedMs });
      }
      record.build.push({ arm, round, rows });
      record.query.push({ arm, round, ...run(product, corpus, 'query', '', id) });
      for (const query of queries[id].slice(0, 2)) {
        const resourcePath = join(work, `${id}-${arm}-cli.json`); const start = performance.now();
        const result = JSON.parse(execFileSync(process.execPath, [join(product, 'dist/bin/julius.js'), 'ask', query, corpus, '--json', '--no-refresh'],
          { cwd: corpus, env: { ...env, JULIUS_SELECTIVE_RESOURCES: resourcePath }, encoding: 'utf8', timeout: 60000, maxBuffer: 8 * 1024 * 1024 }));
        record.cli.push({ arm, round, query, elapsedMs: performance.now() - start, hash: sha(JSON.stringify(result)), ...JSON.parse(readFileSync(resourcePath)) });
      }
    }
    const b = record.build.find(x => x.round === round && x.arm === 'baseline').rows;
    const c = record.build.find(x => x.round === round && x.arm === 'candidate').rows;
    assert.deepEqual(c.map(x => [x.phase, x.graphHash, x.lexicalHash, x.parsed, x.reused]), b.map(x => [x.phase, x.graphHash, x.lexicalHash, x.parsed, x.reused]), 'Graph/index/incremental parity');
    assert.equal(c[0].counters.files, c[0].parsed, 'Every full-build file must use Rust in these corpora');
    assert.equal(c[1].counters.files, 0, 'Unchanged build must reuse extraction');
    assert.equal(c[2].counters.files, 1, 'Edit must extract exactly one file');
    assert.deepEqual(record.query.find(x => x.round === round && x.arm === 'candidate').parity, record.query.find(x => x.round === round && x.arm === 'baseline').parity, 'Complete AskResult parity');
    assert.deepEqual(record.cli.filter(x => x.round === round && x.arm === 'candidate').map(x => x.hash), record.cli.filter(x => x.round === round && x.arm === 'baseline').map(x => x.hash), 'CLI parity');
  }
  for (let round = 0; round < 2; round++) for (const [arm, product] of round % 2 ? Object.entries(arms).reverse() : Object.entries(arms)) {
    const resources = join(work, `mcp-${round}-${arm}.json`);
    record.mcp.push({ arm, round, ...await mcp(product, corpus, queries[id][0], round, arm), ...JSON.parse(readFileSync(resources)) });
  }
  assert.deepEqual(record.mcp.filter(x => x.arm === 'candidate').flatMap(x => x.rows.map(r => r.hash)), record.mcp.filter(x => x.arm === 'baseline').flatMap(x => x.rows.map(r => r.hash)), 'MCP evidence parity');
  report.corpora.push(record); json(join(output, 'report.json'), report);
}
assert.equal(treeHash(join(repo, 'src')), sourceHash, 'Production sources changed');
for (const [arm, root] of Object.entries(arms)) assert.equal(treeHash(join(root, 'dist')), report.runtimeHashes[arm], 'Frozen build changed');
assert.equal(sha(readFileSync(join(here, 'extractor.node'))), report.addonSha256, 'Native build changed');
assert.equal(readFileSync(guard, 'utf8'), '', 'Offline guard recorded an external operation');
report.validation = { productionSourceUnchanged: true, frozenRuntimeUnchanged: true, nativeBinaryUnchanged: true, offlineGuardEmpty: true };
json(join(output, 'report.json'), report);
console.log(`Completed: ${join(output, 'report.json')}`);
