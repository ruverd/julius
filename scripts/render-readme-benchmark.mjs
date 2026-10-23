import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';

const reportUrl = new URL('../docs/strategy/recovery-impact-comparison.json', import.meta.url);
const outputUrl = new URL('../docs/assets/context-benchmark.svg', import.meta.url);
const readmeUrl = new URL('../README.md', import.meta.url);
const report = JSON.parse(readFileSync(reportUrl, 'utf8'));
const arms = ['trail', 'policy'].map(arm => {
  const rows = report.summary.filter(row => row.arm === arm);
  assert.ok(rows.length > 0, `Missing benchmark arm: ${arm}`);
  assert.equal(new Set(rows.map(row => row.task)).size, rows.length);
  for (const row of rows) {
    assert.ok(Number.isSafeInteger(row.totalTokens) && row.totalTokens >= 0);
    assert.ok(Number.isSafeInteger(row.runs) && row.runs > 0);
    assert.equal(row.passed, row.runs, `Evidence check failed: ${arm}/${row.task}`);
    const trials = report.results.filter(trial => trial.arm === arm && trial.task === row.task);
    assert.equal(trials.length, row.runs, `Trial count differs: ${arm}/${row.task}`);
    assert.equal(trials.filter(trial => trial.quality === true).length, row.passed);
    assert.equal(trials.reduce((sum, trial) => sum + trial.totalTokens, 0), row.totalTokens);
  }
  return {
    rows,
    tasks: rows.map(row => row.task).sort(),
    passed: rows.reduce((sum, row) => sum + row.passed, 0),
    runs: rows.reduce((sum, row) => sum + row.runs, 0),
    tokens: rows.reduce((sum, row) => sum + row.totalTokens, 0),
  };
});
const [upstream, julius] = arms;
assert.deepEqual(upstream.tasks, julius.tasks);
assert.equal(upstream.runs, julius.runs);
for (const row of upstream.rows) {
  assert.equal(row.runs, julius.rows.find(candidate => candidate.task === row.task).runs);
}
assert.ok(upstream.tokens > 0);
assert.equal(report.encoding, 'cl100k_base');
assert.equal(report.providerUsage, null);
assert.equal(report.providerCost, null);
assert.equal(report.codingAccuracy, null);
assert.match(report.candidate.revision, /^[a-f0-9]{40}$/);
const revision = report.candidate.revision.slice(0, 7);
const format = value => value.toLocaleString('en-US');
const difference = ((upstream.tokens - julius.tokens) / upstream.tokens * 100);
const headline = difference >= 0
  ? `${difference.toFixed(1)}% fewer protocol tokens`
  : `${Math.abs(difference).toFixed(1)}% more protocol tokens`;
const taskLabels = {
  tiny: 'Read a small result',
  selective: 'Retrieve one required fact',
  complete: 'Request complete output',
  impact: 'Trace callers',
  'absent-focus': 'Recover after a missing focus',
  'ambiguous-focus': 'Resolve an ambiguous focus',
  'without-hint': 'Recover all output without a hint',
  'after-edit': 'Refresh after a source edit',
  'investigation-impact': 'Compose a change-impact report',
  'warm-session': 'Query in a warm session',
};
assert.deepEqual(Object.keys(taskLabels).sort(), upstream.tasks);
const tasks = upstream.rows.map(row => {
  const candidate = julius.rows.find(candidate => candidate.task === row.task);
  assert.ok(row.totalTokens > 0);
  return {
    id: row.task,
    label: taskLabels[row.task],
    runs: row.runs,
    upstream: row.totalTokens,
    julius: candidate.totalTokens,
    reduction: (row.totalTokens - candidate.totalTokens) / row.totalTokens * 100,
  };
});
const pythonRecovery = ['trail', 'policy'].map(arm => report.results
  .filter(trial => trial.arm === arm && trial.task === 'without-hint' && trial.language === 'python')
  .reduce((sum, trial) => sum + trial.totalTokens, 0));
assert.ok(pythonRecovery[0] > 0 && pythonRecovery[1] > 0);
const pythonChange = (pythonRecovery[1] - pythonRecovery[0]) / pythonRecovery[0] * 100;
const pythonResult = `${Math.abs(pythonChange).toFixed(1)}% ${pythonChange >= 0 ? 'more' : 'fewer'}`;
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
const maxRatio = Math.max(1, ...tasks.map(task => task.julius / task.upstream));
const taskBars = tasks.map((task, index) => {
  const y = 406 + index * 35;
  const baselineWidth = 210 / maxRatio;
  const width = baselineWidth * task.julius / task.upstream;
  return `<text x="40" y="${y + 10}" fill="#e0e0e0" font-size="15">${task.label}</text>
    <rect x="330" y="${y}" width="${baselineWidth}" height="12" rx="2" fill="#767676"/>
    <rect x="330" y="${y}" width="${width.toFixed(2)}" height="12" rx="2" fill="#f5f5f5"/>
    <text x="665" y="${y + 10}" text-anchor="end">${format(task.upstream)}</text>
    <text x="785" y="${y + 10}" text-anchor="end">${format(task.julius)}</text>
    <text x="920" y="${y + 10}" text-anchor="end">${task.reduction.toFixed(1)}%</text>`;
}).join('\n    ');
const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="846" viewBox="0 0 960 846" role="img" aria-labelledby="title description">
  <title id="title">${headline} in the recorded offline comparison</title>
  <desc id="description">Recorded Julius revision ${report.candidate.revision}, prepared for 0.24.1. Pinned upstream: ${format(upstream.tokens)} tokens. Julius selective/complete policy: ${format(julius.tokens)} tokens. ${upstream.tasks.length} synthetic task types, ${upstream.runs} executions per arm. Both arms passed ${upstream.passed} evidence checks. Counts include initialization, discovery, invocation, and recovery. Each task bar compares Julius in white with its upstream baseline in gray; scales differ across tasks. Python no-hint recovery uses ${pythonResult} tokens. Provider usage, cost, and coding accuracy were not measured.</desc>
  <rect width="960" height="846" rx="12" fill="#0d0d0d"/>
  <g font-family="Arial, Helvetica, sans-serif">
    <text x="40" y="54" fill="#f5f5f5" font-size="29" font-weight="700">${headline}</text>
    <text x="40" y="87" fill="#b5b5b5" font-size="16">${upstream.tasks.length} synthetic task types · ${upstream.runs} executions per arm · all evidence checks passed</text>
    <g fill="#a0a0a0" font-size="14">
    ${ticks}
    </g>
    ${bars}
    <g fill="#b5b5b5" font-size="14">
      <text x="40" y="370">Each task · nine executions · white = Julius, gray = upstream</text>
      <text x="665" y="390" text-anchor="end">Upstream</text>
      <text x="785" y="390" text-anchor="end">Julius</text>
      <text x="920" y="390" text-anchor="end">Fewer tokens</text>
      ${taskBars}
    </g>
    <text x="40" y="777" fill="#c7c7c7" font-size="15">Python no-hint recovery: ${pythonResult} tokens. Per-task bars use separate baseline scales.</text>
    <text x="40" y="803" fill="#a0a0a0" font-size="14">Julius ${revision} · offline cl100k_base · provider cost, speed, and coding accuracy unmeasured.</text>
  </g>
</svg>
`;
const summary = `**${headline}** in a [recorded offline MCP benchmark](#benchmarks).
${upstream.tasks.length} task types, three languages, ${upstream.runs} executions per variant. Every declared evidence check passed.`;
const table = tasks.map(task =>
  `| ${task.label} | ${format(task.upstream)} | ${format(task.julius)} | ${task.reduction.toFixed(1)}% |`
).join('\n');
const benchmark = `**${headline}**, with all declared evidence checks passing in both variants.
Julius uses **${format(upstream.tokens - julius.tokens)} fewer tokens** across the recorded task mix.

| Metric | Pinned upstream | Julius | Change |
| --- | ---: | ---: | ---: |
| Total protocol tokens | ${format(upstream.tokens)} | ${format(julius.tokens)} | **${difference.toFixed(1)}% fewer** |
| Mean protocol tokens per execution | ${format(Math.round(upstream.tokens / upstream.runs))} | ${format(Math.round(julius.tokens / julius.runs))} | ${difference.toFixed(1)}% fewer |
| Executions passing evidence checks | ${upstream.passed}/${upstream.runs} | ${julius.passed}/${julius.runs} | All passed |

![Offline MCP benchmark: ${format(upstream.tokens)} upstream protocol tokens versus ${format(julius.tokens)} for Julius. All ten task results shown below.](docs/assets/context-benchmark.svg)

**What ran:** ten synthetic evidence tasks in TypeScript, Python, and Go, with
three repetitions per task and language. Counts include MCP initialization,
schema discovery, requests, responses, and every recovery call. Julius follows
the recorded selective/complete policy. Both variants face the same evidence checks.

<details>
<summary>All ten tasks: protocol tokens across nine executions each</summary>

| Task | Pinned upstream | Julius | Fewer tokens |
| --- | ---: | ---: | ---: |
${table}
| **Total** | **${format(upstream.tokens)}** | **${format(julius.tokens)}** | **${difference.toFixed(1)}%** |

</details>

**Where the gain shrinks:** recovering all output without a hint saves only
${tasks.find(task => task.id === 'without-hint').reduction.toFixed(1)}% across languages. Python uses **${pythonResult}** tokens in that task.
Complete-byte recovery verifies the captured object's digest. Composed impact
checks verify required caller identities. These checks do not measure coding accuracy.

**Measurement scope:** offline \`cl100k_base\` counts of JSON-RPC NDJSON traffic.
Provider usage, dollar cost, agent speed, and real issue resolution remain unmeasured.
The scripted policy does not establish which tools a model chooses autonomously.

Measured Julius source: [\`${revision}\`](https://github.com/ruverd/julius/commit/${report.candidate.revision}),
prepared for \`0.24.1\`, against the [pinned upstream executable](PROVENANCE.md).
Read the [method and reproduction steps](docs/strategy/recovery-impact-comparison.md),
[raw results](docs/strategy/recovery-impact-comparison.json), or
[protocol traces](docs/strategy/recovery-impact-comparison.traces.json.gz).
The [earlier comparison](docs/strategy/performance-comparison.md) remains available.

Regenerate the summary, tables, and chart with \`node scripts/render-readme-benchmark.mjs\`.
Verify them with \`node scripts/render-readme-benchmark.mjs --check\`.`;
let readme = readFileSync(readmeUrl, 'utf8');
for (const [name, body] of [['summary', summary], ['results', benchmark]]) {
  const start = `<!-- benchmark:${name}:start -->`;
  const end = `<!-- benchmark:${name}:end -->`;
  assert.equal(readme.split(start).length, 2, `Expected one ${start}`);
  assert.equal(readme.split(end).length, 2, `Expected one ${end}`);
  const from = readme.indexOf(start);
  const to = readme.indexOf(end);
  assert.ok(to > from);
  readme = readme.slice(0, from) + `${start}\n${body}\n` + readme.slice(to);
}
if (process.argv.includes('--check')) {
  assert.equal(readFileSync(outputUrl, 'utf8'), svg, 'README benchmark chart is stale');
  assert.equal(readFileSync(readmeUrl, 'utf8'), readme, 'README benchmark text is stale');
  console.log('README benchmark summary, tables, and chart match the recorded JSON.');
} else {
  writeFileSync(outputUrl, svg);
  writeFileSync(readmeUrl, readme);
  console.log('Updated README benchmark summary, tables, and chart from the recorded JSON.');
}
