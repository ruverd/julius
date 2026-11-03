import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gunzipSync } from 'node:zlib';

const here = dirname(fileURLToPath(import.meta.url));
const output = resolve(process.argv[2] ?? 'docs/strategy/rust-extractor');
const reportBytes = existsSync(join(output, 'report.json')) ? readFileSync(join(output, 'report.json')) : gunzipSync(readFileSync(join(output, 'report.json.gz')));
const report = JSON.parse(reportBytes);
const sha = x => createHash('sha256').update(x).digest('hex');
for (const [file, key] of [['worker.mjs', 'workerSha256'], ['adapter.mjs', 'adapterSha256'], ['extractor.node', 'addonSha256']]) {
  assert.equal(sha(readFileSync(join(here, file))), report[key], `${file} changed`);
}
const plan = { version: 1, date: new Date().toISOString(), initialReportSha256: sha(reportBytes),
  corpus: 'commander', phase: 'unchanged', rounds: 12,
  reason: 'Initial four-round pilot observed an unchanged-build regression above its 10% gate. Repeat only this unresolved case with rotated order, no concurrent test suites. Initial gate remains recorded; this is not a new release gate.',
  rows: [] };
writeFileSync(join(output, 'unchanged-confirmation-plan.json'), JSON.stringify(plan, null, 2) + '\n');
const guard = join(report.work, 'confirmation-offline.log'); writeFileSync(guard, '');
const env = { PATH: process.env.PATH, HOME: join(report.work, 'home'), USERPROFILE: join(report.work, 'home'), CI: '1', DO_NOT_TRACK: '1',
  JULIUS_PROBE_GUARD_LOG: guard, JULIUS_RUST_ADDON: join(here, 'extractor.node'),
  NODE_OPTIONS: `--require=${join(here, '../offline-guard.cjs')}` };
for (let round = 0; round < plan.rounds; round++) for (const arm of round % 2 ? ['candidate', 'baseline'] : ['baseline', 'candidate']) {
  const result = JSON.parse(execFileSync(process.execPath, ['--expose-gc', join(here, 'worker.mjs'), join(report.work, arm), join(report.work, 'corpora/commander'), 'build', 'unchanged', 'commander'],
    { env, encoding: 'utf8', timeout: 60000 }));
  assert.equal(result.rows[0].parsed, 0); assert.equal(result.rows[0].reused, 8);
  plan.rows.push({ arm, round, ...result.rows[0] });
}
assert.equal(new Set(plan.rows.map(x => x.graphHash)).size, 1);
assert.equal(new Set(plan.rows.map(x => x.lexicalHash)).size, 1);
assert.equal(readFileSync(guard, 'utf8'), '');
const median = list => { const a = [...list].sort((x, y) => x - y); return (a[a.length / 2 - 1] + a[a.length / 2]) / 2; };
const baseline = median(plan.rows.filter(x => x.arm === 'baseline').map(x => x.elapsedMs));
const candidate = median(plan.rows.filter(x => x.arm === 'candidate').map(x => x.elapsedMs));
plan.summary = { baselineMs: baseline, candidateMs: candidate, reduction: 1 - candidate / baseline, exactGraphAndIndexParity: true,
  initialGateChanged: false, offlineGuardEmpty: true };
writeFileSync(join(output, 'unchanged-confirmation.json'), JSON.stringify(plan, null, 2) + '\n');
console.log(JSON.stringify(plan.summary));
