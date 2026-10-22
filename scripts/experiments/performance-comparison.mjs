import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';
import { selectTasks } from './performance-contract.mjs';
import { runArm, verifyUpstream } from './local-comparison.mjs';
export { completeBody, deliveryArguments, comparisonDecision } from './performance-contract.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const candidateRoot = resolve(here, '../..');
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const manifestPath = join(here, 'performance-tasks.json');
const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
const median = values => { const sorted = [...values].sort((a, b) => a - b); return sorted[Math.floor(sorted.length / 2)]; };

export async function runPerformanceComparison(trailRoot, beforeRoot, output, taskIds) {
  const tasks = selectTasks(manifest.tasks, taskIds);
  const upstream = verifyUpstream(trailRoot);
  assert.equal(execFileSync('git', ['rev-parse', 'HEAD'], { cwd: beforeRoot, encoding: 'utf8' }).trim(), execFileSync('git', ['rev-parse', '0376b7e'], { cwd: candidateRoot, encoding: 'utf8' }).trim(), 'Before revision');
  for (const root of [beforeRoot, candidateRoot]) assert.ok(readFileSync(join(root, 'dist/bin/julius.js')).length);
  const workspace = mkdtempSync(join(tmpdir(), 'julius-performance-'));
  const runs = [];
  const treeHash = (root, subtree) => {
    const files = [];
    const walk = dir => { for (const item of readdirSync(dir, { withFileTypes: true })) { const path = join(dir, item.name); if (item.isDirectory()) walk(path); else files.push(path); } };
    walk(join(root, subtree));
    return hash(JSON.stringify(files.sort().map(path => [path.slice(root.length + 1), hash(readFileSync(path))])));
  };
  const sourceHash = root => treeHash(root, 'src');
  const distHash = root => treeHash(root, 'dist');
  const inputs = Object.fromEntries([['trail', trailRoot], ['before', beforeRoot], ['candidate', candidateRoot]].map(([name, root]) => [name, { sourceSha256: sourceHash(root), distSha256: distHash(root) }]));
  try {
    for (let repetition = 0; repetition < manifest.repetitions; repetition++) {
      for (const language of manifest.languages) for (const task of tasks) {
        const arms = ['trail', 'compact-1200', 'policy', 'policy-known-schema'];
        const rotate = (repetition + runs.length / 4) % arms.length;
        const ordered = [...arms.slice(rotate), ...arms.slice(0, rotate)];
        for (const arm of ordered) {
          process.stderr.write(`${repetition}/${language}/${task.id ?? task.kind}/${arm}\n`);
          runs.push({ repetition, ...await runArm(trailRoot, workspace, language, task, arm, {
            repetition, manifest, productRoot: arm === 'compact-1200' ? beforeRoot : candidateRoot,
            policy: arm.startsWith('policy'), knownSchemas: arm === 'policy-known-schema',
          }) });
        }
      }
    }
  } finally { rmSync(workspace, { recursive: true, force: true }); }
  const summary = [];
  for (const task of tasks) for (const arm of ['trail', 'compact-1200', 'policy', 'policy-known-schema']) {
    const selected = runs.filter(r => r.task === (task.id ?? task.kind) && r.arm === arm);
    summary.push({ task: task.id ?? task.kind, arm, runs: selected.length, passed: selected.filter(r => r.quality).length,
      totalTokens: selected.some(r => r.totalTokens === null) ? null : selected.reduce((s, r) => s + r.totalTokens, 0),
      recoveryCalls: selected.reduce((s, r) => s + r.recoveryCalls, 0), medianBuildMs: median(selected.map(r => r.buildMs)),
      medianRetrievalMs: median(selected.map(r => r.retrievalMs)), medianStartupMs: median(selected.map(r => r.startupMs)),
    });
  }
  const revision = root => execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim();
  const report = { version: 1, upstream, selectedTaskIds: tasks.map(task => task.id ?? task.kind), inputs, before: { revision: revision(beforeRoot), sourceSha256: inputs.before.sourceSha256 },
    candidate: { revision: revision(candidateRoot), sourceSha256: inputs.candidate.sourceSha256, lockSha256: hash(readFileSync(join(candidateRoot, 'package-lock.json'))) },
    manifestSha256: hash(readFileSync(manifestPath)), harnessSha256: hash(readFileSync(fileURLToPath(import.meta.url))), contractSha256: hash(readFileSync(join(here, 'performance-contract.mjs'))), fixtureManifestSha256: hash(readFileSync(join(here, 'local-comparison-tasks.json'))),
    sharedHarnessSha256: hash(readFileSync(join(here, 'local-comparison.mjs'))), node: process.version, encoding: 'cl100k_base',
    providerUsage: null, providerCost: null, codingAccuracy: null,
    scope: 'Actual CLI/MCP processes; scripted synthetic evidence tasks, three repetitions, rotated arm order. All NDJSON requests/responses counted once, including discovery/errors/recovery. Known-schema arm removes discovery only in the harness; not a new advertised tool or measured host adoption. Retrieval timing sums tool request-to-response latency, excluding harness tokenization; build and startup reported separately. No model, reasoning, provider prompt replay or paid calls. Operating-system cache not controlled.',
    summary, results: runs.map(({ events, ...run }) => run) };
  for (const [name, root] of [['trail', trailRoot], ['before', beforeRoot], ['candidate', candidateRoot]]) {
    assert.equal(sourceHash(root), inputs[name].sourceSha256, `${name} source changed during experiment`);
    assert.equal(distHash(root), inputs[name].distSha256, `${name} binary changed during experiment`);
  }
  mkdirSync(dirname(output), { recursive: true });
  writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
  writeFileSync(output.replace(/\.json$/, '.traces.json.gz'), gzipSync(JSON.stringify(runs.map(({ events, language, task, arm, repetition }) => ({ events, language, task, arm, repetition }))) + '\n'));
  return report;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [, , trail, before, output, taskIds] = process.argv;
  if (!trail || !before || !output) throw new Error('Usage: node scripts/experiments/performance-comparison.mjs <built-trail> <built-before> <report.json>');
  const report = await runPerformanceComparison(resolve(trail), resolve(before), resolve(output), taskIds?.split(','));
  console.log(JSON.stringify(report.summary, null, 2));
}
