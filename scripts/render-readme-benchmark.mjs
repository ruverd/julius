import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';

const reportUrl = new URL('../docs/strategy/performance-comparison.json', import.meta.url);
const outputUrl = new URL('../docs/assets/context-benchmark.svg', import.meta.url);
const report = JSON.parse(readFileSync(reportUrl, 'utf8'));
const arms = ['trail', 'policy'].map(arm => {
  const rows = report.summary.filter(row => row.arm === arm);
  assert.ok(rows.length > 0, `Missing benchmark arm: ${arm}`);
  assert.equal(new Set(rows.map(row => row.task)).size, rows.length);
  for (const row of rows) {
    assert.ok(Number.isSafeInteger(row.totalTokens) && row.totalTokens >= 0);
    assert.ok(Number.isSafeInteger(row.runs) && row.runs > 0);
    assert.equal(row.passed, row.runs, `Evidence check failed: ${arm}/${row.task}`);
  }
  return {
    tasks: rows.map(row => row.task).sort(),
    runs: rows.reduce((sum, row) => sum + row.runs, 0),
    tokens: rows.reduce((sum, row) => sum + row.totalTokens, 0),
  };
});
const [upstream, julius] = arms;
assert.deepEqual(upstream.tasks, julius.tasks);
assert.equal(upstream.runs, julius.runs);
assert.ok(upstream.tokens > 0);
assert.equal(report.encoding, 'cl100k_base');
assert.match(report.candidate.revision, /^[a-f0-9]{40}$/);
const revision = report.candidate.revision.slice(0, 7);
const format = value => value.toLocaleString('en-US');
const difference = ((upstream.tokens - julius.tokens) / upstream.tokens * 100);
const headline = difference >= 0
  ? `${difference.toFixed(1)}% fewer protocol tokens`
  : `${Math.abs(difference).toFixed(1)}% more protocol tokens`;
const ceiling = Math.ceil(Math.max(upstream.tokens, julius.tokens) / 100000) * 100000;
const x = 235;
const plotWidth = 620;
const ticks = Array.from({ length: 6 }, (_, i) => {
  const value = ceiling * i / 5;
  const position = x + plotWidth * i / 5;
  return `<line x1="${position}" y1="133" x2="${position}" y2="298" stroke="#252525"/>
    <text x="${position}" y="324" text-anchor="middle">${i === 0 ? '0' : `${value / 1000}k`}</text>`;
}).join('\n    ');
const bars = [
  { label: 'Pinned upstream', value: upstream.tokens, y: 151, fill: '#767676' },
  { label: 'Julius', value: julius.tokens, y: 241, fill: '#f5f5f5' },
].map(({ label, value, y, fill }) => {
  const width = Number((value / ceiling * plotWidth).toFixed(2));
  return `<text x="40" y="${y + 29}" fill="#f5f5f5" font-size="19">${label}</text>
    <rect x="${x}" y="${y}" width="${width}" height="44" rx="3" fill="${fill}"/>
    <text x="${x + width + 12}" y="${y + 28}" fill="#f5f5f5" font-size="17">${format(value)}</text>`;
}).join('\n    ');
const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="436" viewBox="0 0 960 436" role="img" aria-labelledby="title description">
  <title id="title">${headline} in the recorded offline comparison</title>
  <desc id="description">Historical Julius revision ${report.candidate.revision}, not the current release. Pinned upstream: ${format(upstream.tokens)} tokens. Julius selective/complete policy: ${format(julius.tokens)} tokens. ${upstream.tasks.length} synthetic task types, ${upstream.runs} executions per arm. Counts include initialization, discovery, invocation, and recovery. Provider usage, cost, and coding accuracy were not measured.</desc>
  <rect width="960" height="436" rx="12" fill="#0d0d0d"/>
  <g font-family="Arial, Helvetica, sans-serif">
    <text x="40" y="54" fill="#f5f5f5" font-size="29" font-weight="700">${headline}</text>
    <text x="40" y="87" fill="#b5b5b5" font-size="16">Historical run · ${upstream.tasks.length} synthetic task types · ${upstream.runs} executions per arm · lower is better</text>
    <g fill="#a0a0a0" font-size="14">
    ${ticks}
    </g>
    ${bars}
    <text x="40" y="378" fill="#c7c7c7" font-size="15">Julius ${revision} · offline cl100k_base counts over complete JSON-RPC NDJSON traffic.</text>
    <text x="40" y="405" fill="#a0a0a0" font-size="14">Synthetic evidence recovery. Provider usage, cost, and coding accuracy unmeasured.</text>
  </g>
</svg>
`;
if (process.argv.includes('--check')) {
  assert.equal(readFileSync(outputUrl, 'utf8'), svg, 'README benchmark chart is stale');
  console.log('README benchmark chart matches the recorded JSON.');
} else {
  writeFileSync(outputUrl, svg);
  console.log('Wrote docs/assets/context-benchmark.svg from the recorded JSON.');
}
