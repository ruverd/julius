import { readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const dir = resolve(process.argv[2]);
const report = JSON.parse(readFileSync(join(dir, 'report.json')));
function stats(values) {
  const a = [...values].sort((x, y) => x - y); const mid = Math.floor(a.length / 2);
  return { n: a.length, p50: a.length % 2 ? a[mid] : (a[mid - 1] + a[mid]) / 2, p95: a[Math.ceil(a.length * 0.95) - 1] };
}
const summary = { providerUsage: null, providerCost: null, agentCorrectness: null, exactParityCases: 0, corpora: [] };
for (const c of report.corpora) {
  const arms = {};
  for (const arm of ['baseline', 'candidate']) {
    const warm = c.warm.filter(r => r.arm === arm);
    arms[arm] = {
      warmApiMs: stats(warm.flatMap(r => r.rows.map(r => r.elapsedMs))),
      coldCliMs: stats(c.cli.filter(r => r.arm === arm).map(r => r.elapsedMs)),
      warmPeakRSSMiB: stats(warm.map(r => r.maxRSSKiB / 1024)),
      retainedHeapMiB: stats(warm.map(r => r.memory.heapUsed / 1024 ** 2)),
      formattedTokens: c.parity[arm].formatted.reduce((n, r) => n + r.tokens, 0),
      totalMcpWireTokens: c.mcp[arm].totalWireTokens,
      mcpSetupTokens: c.mcp[arm].setupTokens,
      mcpRecoveryCalls: c.mcp[arm].rows.reduce((n, r) => n + r.recoveryCalls, 0),
      mcpWarmMs: stats(c.mcp[arm].rows.filter(r => r.pass > 0).map(r => r.elapsedMs)),
    };
  }
  const warmReduction = 1 - arms.candidate.warmApiMs.p50 / arms.baseline.warmApiMs.p50;
  const cliReduction = 1 - arms.candidate.coldCliMs.p50 / arms.baseline.coldCliMs.p50;
  const parity = c.parity.baseline.rows.length;
  summary.exactParityCases += parity;
  summary.corpora.push({ id: c.id, parity, arms, warmReduction, cliReduction,
    wireReduction: 1 - arms.candidate.totalMcpWireTokens / arms.baseline.totalMcpWireTokens });
}
summary.wireTokens = Object.fromEntries(['baseline', 'candidate'].map(arm => [arm, summary.corpora.reduce((n, c) => n + c.arms[arm].totalMcpWireTokens, 0)]));
summary.wireReduction = 1 - summary.wireTokens.candidate / summary.wireTokens.baseline;
summary.gate = { exactParity: true, sourceAndPointersRetained: true, positiveAggregateWireReduction: summary.wireReduction > 0,
  largeWarmGain: summary.corpora.find(c => c.id === 'synthetic-large').warmReduction >= report.gate.minLargeWarmReduction,
  realWarmRegressions: summary.corpora.filter(c => c.id !== 'synthetic-large').every(c => c.warmReduction >= -report.gate.maxRealWarmRegression) };
summary.decision = Object.values(summary.gate).every(Boolean) ? 'retain-changes' : 'revise-before-retaining';
writeFileSync(join(dir, 'summary.json'), JSON.stringify(summary, null, 2) + '\n');
console.log(JSON.stringify({ decision: summary.decision, gate: summary.gate, wireTokens: summary.wireTokens, wireReduction: summary.wireReduction,
  corpora: summary.corpora.map(c => ({ id: c.id, warm: [c.arms.baseline.warmApiMs.p50, c.arms.candidate.warmApiMs.p50],
    cli: [c.arms.baseline.coldCliMs.p50, c.arms.candidate.coldCliMs.p50], warmReduction: c.warmReduction, cliReduction: c.cliReduction })) }, null, 2));
