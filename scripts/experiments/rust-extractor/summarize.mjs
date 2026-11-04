import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gunzipSync } from 'node:zlib';

const here = dirname(fileURLToPath(import.meta.url));
const output = resolve(process.argv[2] ?? 'docs/strategy/rust-extractor');
const reportBytes = existsSync(join(output, 'report.json')) ? readFileSync(join(output, 'report.json')) : gunzipSync(readFileSync(join(output, 'report.json.gz')));
const report = JSON.parse(reportBytes);
const sha = value => createHash('sha256').update(value).digest('hex');
for (const [path, key] of [['pilot.mjs', 'harnessSha256'], ['worker.mjs', 'workerSha256'], ['adapter.mjs', 'adapterSha256'], ['src/lib.rs', 'rustSha256']]) {
  assert.equal(sha(readFileSync(join(here, path))), report[key], `${path} changed after timing`);
}
export function median(values) {
  const sorted = [...values].sort((a, b) => a - b); const i = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[i] : (sorted[i - 1] + sorted[i]) / 2;
}
function comparison(baseline, candidate) {
  const b = median(baseline); const c = median(candidate);
  return { baseline: b, candidate: c, reduction: 1 - c / b, speedup: b / c, observationsPerArm: baseline.length };
}
const result = { version: 1, reportSha256: sha(reportBytes), gate: report.gate, corpora: [] };
for (const corpus of report.corpora) {
  const buildRows = arm => corpus.build.filter(x => x.arm === arm).flatMap(x => x.rows);
  const build = Object.fromEntries(['full', 'unchanged', 'one-file-edit', 'addition', 'deletion'].map(phase => [phase,
    Object.fromEntries(['elapsedMs', 'processElapsedMs', 'maxRSSKiB'].map(field => [field, comparison(...['baseline', 'candidate'].map(arm => buildRows(arm).filter(x => x.phase === phase).map(x => x[field])))])),
  ]));
  const full = buildRows('baseline').find(x => x.phase === 'full');
  const warm = comparison(...['baseline', 'candidate'].map(arm => corpus.query.filter(x => x.arm === arm).flatMap(x => x.rows.map(r => r.elapsedMs))));
  const cli = Object.fromEntries(['elapsedMs', 'maxRSSKiB'].map(field => [field, comparison(...['baseline', 'candidate'].map(arm => corpus.cli.filter(x => x.arm === arm).map(x => x[field])))]));
  const mcp = comparison(...['baseline', 'candidate'].map(arm => corpus.mcp.filter(x => x.arm === arm).flatMap(x => x.rows.filter(r => r.pass > 0).map(r => r.elapsedMs))));
  const queryRSSKiB = comparison(...['baseline', 'candidate'].map(arm => corpus.query.filter(x => x.arm === arm).map(x => x.maxRSSKiB)));
  const gates = {
    fullBuild: build.full.elapsedMs.reduction >= report.gate.minRealFullBuildReduction,
    incremental: Object.values(build).slice(1).every(x => x.elapsedMs.reduction >= -report.gate.maxIncrementalRegression),
    warmQuery: warm.reduction >= -report.gate.maxWarmQueryRegression,
    buildPeakRSS: Object.values(build).every(x => x.maxRSSKiB.reduction >= -report.gate.maxBuildPeakRSSRegression),
  };
  result.corpora.push({ id: corpus.id, files: full.parsed, nodes: full.nodes, edges: full.edges,
    exactExtractionCases: corpus.extraction.baseline.cases, queryCasesPerRound: corpus.query[0].parity.length,
    build, warm, queryRSSKiB, cli, mcp, gates,
    rustFullCountersMedian: Object.fromEntries(['files', 'nativeMs', 'materializeMs', 'bytes'].map(key => [key,
      median(buildRows('candidate').filter(r => r.phase === 'full').map(r => r.counters[key]))])),
  });
}
result.allGatesPass = result.corpora.every(c => Object.values(c.gates).every(Boolean));
result.validation = report.validation;
writeFileSync(join(output, 'summary.json'), JSON.stringify(result, null, 2) + '\n');
for (const c of result.corpora) {
  console.log(`${c.id}: ${c.files} files / ${c.nodes} nodes / ${c.edges} edges`);
  for (const [phase, metrics] of Object.entries(c.build)) console.log(`  ${phase}: ${metrics.elapsedMs.baseline.toFixed(2)} -> ${metrics.elapsedMs.candidate.toFixed(2)} ms (${metrics.elapsedMs.speedup.toFixed(2)}x), RSS ${(metrics.maxRSSKiB.baseline / 1024).toFixed(1)} -> ${(metrics.maxRSSKiB.candidate / 1024).toFixed(1)} MiB`);
  console.log(`  warm API: ${c.warm.baseline.toFixed(2)} -> ${c.warm.candidate.toFixed(2)} ms; CLI ${c.cli.elapsedMs.baseline.toFixed(2)} -> ${c.cli.elapsedMs.candidate.toFixed(2)}; MCP ${c.mcp.baseline.toFixed(2)} -> ${c.mcp.candidate.toFixed(2)}`);
  console.log(`  gates: ${JSON.stringify(c.gates)}`);
}
console.log(`All local gates pass: ${result.allGatesPass}`);
