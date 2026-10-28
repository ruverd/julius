import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir, cpus } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { buildGraph } from '../../dist/graph/build.js';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const output = resolve(process.argv[2] ?? 'lexical-cache-benchmark.json');
const queries = JSON.parse(readFileSync(join(root, 'scripts/experiments/lexical-cache-queries.json')));
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const ms = start => Number(process.hrtime.bigint() - start) / 1e6;
const median = values => percentile(values, .5);
function percentile(values, q) { const sorted = [...values].sort((a, b) => a - b); return sorted[Math.ceil(sorted.length * q) - 1]; }
const work = mkdtempSync(join(tmpdir(), 'julius-lexical-cache-'));
try {
  const corpus = join(work, 'corpus'); mkdirSync(corpus);
  const paths = execFileSync('git', ['ls-files', '-z', '--', 'src'], { cwd: root, encoding: 'utf8' }).split('\0').filter(path => path.endsWith('.ts')).sort();
  const sources = paths.map(path => ({ path, sha256: hash(readFileSync(join(root, path))) }));
  for (const path of paths) { mkdirSync(dirname(join(corpus, path)), { recursive: true }); cpSync(join(root, path), join(corpus, path)); }
  cpSync(join(root, 'package.json'), join(corpus, 'package.json'));
  const graph = await buildGraph(corpus, { graphOnly: true, reuse: false }); assert.deepEqual(graph.errors, []);
  cpSync(join(root, 'dist'), join(work, 'dist'), { recursive: true });
  writeFileSync(join(work, 'package.json'), '{"type":"module"}'); symlinkSync(join(root, 'node_modules'), join(work, 'node_modules'));
  const currentPath = join(work, 'dist/ask/ask.js');
  const currentCode = readFileSync(currentPath, 'utf8');
  const oldCode = currentCode.replace('import { preparedAskDocs, preparedAskFields } from "./prepared-index.js";\n', '')
    .replace('const map = preparedAskDocs(corpus.askIndex);', 'const map = new Map(corpus.askIndex.docs.map((d) => [d.id, d]));')
    .replace('return { n, ...preparedAskFields(d) };', 'return { n, name: new Map(d.name), path: new Map(d.path), body: new Map(d.body) };');
  assert.ok(!oldCode.includes('preparedAskDocs') && oldCode.includes('new Map(d.name)'), 'Compiled shape changed');
  const oldPath = join(work, 'dist/ask/ask-uncached.js'); writeFileSync(oldPath, oldCode);
  const pathsByArm = { uncached: oldPath, cached: currentPath };
  const arms = {};
  for (const [arm, path] of Object.entries(pathsByArm)) arms[arm] = (await import(pathToFileURL(path))).ask;
  for (const fn of Object.values(arms)) fn(corpus, queries[0]);
  const rows = [];
  for (const query of queries) for (const options of [{ limit: 8 }, { limit: 8, graphRank: false }, { limit: 8, in: 'src/economy/' }, { limit: 8, source: true }, { limit: 8, includeRankingMetadata: true }]) {
    assert.deepEqual(arms.cached(corpus, query, options), arms.uncached(corpus, query, options));
    const timings = { uncached: [], cached: [] };
    for (let rep = 0; rep < 5; rep++) for (const arm of rep % 2 ? ['cached', 'uncached'] : ['uncached', 'cached']) {
      const start = process.hrtime.bigint(); arms[arm](corpus, query, options); timings[arm].push(ms(start));
    }
    rows.push({ query, options, timings });
  }
  const cold = []; const memory = [];
  for (let rep = 0; rep < 7; rep++) for (const arm of rep % 2 ? ['cached', 'uncached'] : ['uncached', 'cached']) {
    const script = `import {ask} from ${JSON.stringify(pathToFileURL(pathsByArm[arm]).href)}; global.gc(); const before=process.memoryUsage().heapUsed; const start=process.hrtime.bigint(); const result=ask(${JSON.stringify(corpus)},${JSON.stringify(queries[0])},{source:true}); const ms=Number(process.hrtime.bigint()-start)/1e6; for(const q of ${JSON.stringify(queries.slice(0,5))}) ask(${JSON.stringify(corpus)},q); global.gc(); console.log(JSON.stringify({ms,heapDelta:process.memoryUsage().heapUsed-before,result}));`;
    const start = process.hrtime.bigint();
    const data = JSON.parse(execFileSync(process.execPath, ['--expose-gc', '--input-type=module', '-e', script], { encoding: 'utf8' }));
    cold.push({ rep, arm, ms: data.ms }); memory.push({ rep, arm, heapDelta: data.heapDelta });
    if (arm === 'uncached') globalThis.expected = data.result;
    else if (globalThis.expected) assert.deepEqual(data.result, globalThis.expected);
    assert.ok(ms(start) > 0);
  }
  const summary = Object.fromEntries(Object.keys(arms).map(arm => [arm, { medianMs: median(rows.flatMap(row => row.timings[arm])), p95Ms: percentile(rows.flatMap(row => row.timings[arm]), .95), coldMedianMs: median(cold.filter(row => row.arm === arm).map(row => row.ms)), retainedHeapDelta: median(memory.filter(row => row.arm === arm).map(row => row.heapDelta)) }]));
  const report = { version: 1, cpu: cpus()[0].model, node: process.version, sources, sourceSha256: hash(JSON.stringify(sources)), harnessSha256: hash(readFileSync(fileURLToPath(import.meta.url))), queriesSha256: hash(JSON.stringify(queries)), compiled: { uncached: hash(oldCode), cached: hash(currentCode) }, scenarios: rows.length, repetitions: 5, scope: 'Offline lexical cache comparison on tracked Julius sources. Baseline reconstructs only pre-cache map creation from current compiled ask. Full-result equality in 230 scenarios. Warm timings exclude MCP/startup. Cold query timing starts after imports in fresh processes, OS caches uncontrolled. Retained heap after queries and forced GC. One corpus; no agent speed or provider usage claim.', providerUsage: null, summary, rows, cold, memory };
  mkdirSync(dirname(output), { recursive: true }); writeFileSync(output, JSON.stringify(report, null, 2) + '\n'); console.log(JSON.stringify(summary, null, 2));
} finally { rmSync(work, { recursive: true, force: true }); }
