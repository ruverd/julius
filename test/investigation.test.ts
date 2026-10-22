import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync, renameSync, statSync, utimesSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runInvestigation, deliverInvestigation } from '../src/investigation/index.js';
import { callCompact, COMPACT_INSTRUCTIONS } from '../src/mcp/compact.js';
import { Economy, economyTokens } from '../src/economy/index.js';
import { loadGraphCached } from '../src/graph/load.js';
import { impactOfMany } from '../src/graph/traverse.js';
import { contextDirFor } from '../src/context/node-file.js';

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'julius-investigation-'));
  writeFileSync(join(root, 'math.ts'), 'export function add(a: number, b: number) { return a + b; }\n');
  writeFileSync(join(root, 'consumer.ts'), 'import { add } from "./math";\nexport function total() { return add(1, 2); }\n');
  return { root, close: () => rmSync(root, { recursive: true, force: true }) };
}
const request = { recipe: 'change-impact' as const, paths: ['math.ts'] };

test('fresh investigation composes file symbols and caller edges, matching inherited graph traversal', async () => {
  const f = fixture();
  try {
    const r = await runInvestigation(f.root, request);
    assert.equal(r.reused, false); assert.equal(r.coverage.traversalComplete, true);
    assert.ok(r.evidence.some(e => e.path === 'consumer.ts' && e.role === 'dependent' && e.via));
    const graph = loadGraphCached(contextDirFor(f.root))!;
    const expected = impactOfMany(graph, graph.nodes.filter(n => n.path === 'math.ts'), 2).filter(h => h.node).map(h => h.id).sort();
    assert.deepEqual(r.evidence.filter(e => e.role === 'dependent').map(e => e.id).sort(), expected);
    assert.match(r.unknowns.join(' '), /does not prove no impact/);
    const again = await runInvestigation(f.root, request);
    assert.equal(again.reused, true);
    assert.deepEqual(again.evidence, r.evidence);
  } finally { f.close(); }
});

test('reuse invalidates on new caller, deleted file, rename and same-size preserved-mtime edit', async () => {
  const f = fixture();
  try {
    const first = await runInvestigation(f.root, request);
    writeFileSync(join(f.root, 'new.ts'), 'import { add } from "./math";\nexport function extra() { return add(3, 4); }\n');
    const added = await runInvestigation(f.root, request);
    assert.equal(added.reused, false); assert.notEqual(added.snapshot, first.snapshot);
    assert.ok(added.evidence.some(e => e.path === 'new.ts'));
    renameSync(join(f.root, 'new.ts'), join(f.root, 'renamed.ts'));
    const renamed = await runInvestigation(f.root, request);
    assert.equal(renamed.reused, false); assert.ok(renamed.evidence.some(e => e.path === 'renamed.ts'));
    assert.ok(!renamed.evidence.some(e => e.path === 'new.ts'));
    rmSync(join(f.root, 'renamed.ts'));
    const deleted = await runInvestigation(f.root, request);
    assert.ok(!deleted.evidence.some(e => e.path === 'renamed.ts'));
    const file = join(f.root, 'math.ts'); const st = statSync(file);
    writeFileSync(file, 'export function add(a: number, b: number) { return a - b; }\n');
    utimesSync(file, st.atime, st.mtime);
    const edited = await runInvestigation(f.root, request);
    assert.equal(edited.reused, false);
    assert.notEqual(edited.snapshot, deleted.snapshot);
    assert.ok(edited.evidence.some(e => e.excerpt.includes('a - b')));
  } finally { f.close(); }
});

test('configuration changes and repository identity prevent invalid reuse', async () => {
  const a = fixture(); const b = fixture();
  try {
    await runInvestigation(a.root, request);
    assert.equal((await runInvestigation(b.root, request)).reused, false);
    writeFileSync(join(a.root, 'tsconfig.json'), '{"compilerOptions":{"strict":true}}');
    assert.equal((await runInvestigation(a.root, request)).reused, false);
    assert.equal((await runInvestigation(a.root, request)).reused, true);
  } finally { a.close(); b.close(); }
});

test('concurrent investigations serialize indexing and reuse verified results', async () => {
  const f = fixture();
  try {
    const [a, b] = await Promise.all([runInvestigation(f.root, request), runInvestigation(f.root, request)]);
    assert.equal(a.reused, false); assert.equal(b.reused, true); assert.deepEqual(a.evidence, b.evidence);
  } finally { f.close(); }
});

test('failure localization searches literal evidence without claiming root cause', async () => {
  const f = fixture();
  try {
    const r = await runInvestigation(f.root, { recipe: 'failure-localization', query: 'add(1, 2)' });
    assert.equal(r.evidence.length, 1); assert.equal(r.evidence[0].path, 'consumer.ts');
    assert.match(r.evidence[0].excerpt, /add\(1, 2\)/);
    assert.match(r.unknowns.join(' '), /not verified root causes/);
    const missing = await runInvestigation(f.root, { recipe: 'failure-localization', query: 'nonexistent' });
    assert.deepEqual(missing.evidence, []);
  } finally { f.close(); }
});

test('MCP validates recipes and arrays, publishes commandless usage instructions', async () => {
  const f = fixture();
  try {
    assert.match(COMPACT_INSTRUCTIONS, /never ask the user to run Julius commands/);
    const discovery = await callCompact(f.root, 'julius_discover', { operation: 'investigation.execute' });
    assert.equal(discovery.isError, false); assert.match(discovery.text, /change-impact/);
    for (const args of [ { recipe: 'shell' }, { recipe: 'change-impact', paths: '../secret' }, { recipe: 'change-impact', paths: ['../secret'] }, { recipe: 'change-impact', paths: [] }, { recipe: 'change-impact', paths: Array(33).fill('math.ts') }, { ...request, depth: 100 }, { ...request, query: 'mixed' }, { recipe: 'failure-localization', query: '' }, { ...request, shell: 'true' } ]) {
      const r = await callCompact(f.root, 'julius_call', { operation: 'investigation.execute', args });
      assert.equal(r.isError, true, JSON.stringify(args));
    }
    const r = await callCompact(f.root, 'julius_call', { operation: 'investigation.execute', args: request, budget: 1200 });
    assert.equal(r.isError, false, r.text); assert.ok(economyTokens(r.text) <= 1200);
  } finally { f.close(); }
});

test('budget selects structured evidence and retains complete report for MCP recovery', async () => {
  const f = fixture();
  try {
    for (let i = 0; i < 50; i++) writeFileSync(join(f.root, `consumer${i}.ts`), `import { add } from "./math";\nexport function fn${i}() { return add(${i}, 2); }\n`);
    const report = await runInvestigation(f.root, request);
    const delivered = await deliverInvestigation(f.root, report, 1200);
    assert.ok(economyTokens(delivered) <= 1200);
    const selected = JSON.parse(delivered);
    assert.ok(selected.omittedEvidence > 0); assert.equal(selected.recover.operation, 'context.read');
    assert.ok(selected.evidence.some((e: any) => e.role === 'dependent'));
    const recovered = await new Economy(f.root).read(selected.handle, { budget: 16000, raw: true });
    assert.deepEqual(JSON.parse(recovered.text), report);
    const tiny = await deliverInvestigation(f.root, report, 256);
    assert.ok(economyTokens(tiny) <= 256); assert.ok(JSON.parse(tiny).handle); assert.doesNotMatch(tiny, /julius read/); assert.equal(JSON.parse(tiny).recover.operation, 'context.read');
  } finally { f.close(); }
});

test('missing or deleted paths retain explicit uncertainty rather than a clean bill of health', async () => {
  const f = fixture();
  try {
    const r = await runInvestigation(f.root, { recipe: 'change-impact', paths: ['deleted.ts'] });
    assert.deepEqual(r.evidence, []); assert.match(r.unknowns.join(' '), /No indexed file/);
  } finally { f.close(); }
});

test('impact delivery groups every identity and edge while retaining the exact detailed report', async () => {
  const f = fixture();
  try {
    writeFileSync(join(f.root, 'consumer.ts'),
      'import { add } from "./math";\n' + Array.from({ length: 24 }, (_, n) => `export function caller${n}() { return add(${n}, 2); }`).join('\n'));
    const report = await runInvestigation(f.root, request);
    const duplicate = report.evidence.find(item => item.name === 'caller0')!;
    duplicate.id += '~2';
    if (duplicate.via) duplicate.via.source = duplicate.id;
    const before = JSON.stringify(report);
    const text = await deliverInvestigation(f.root, report, 1200);
    const selected = JSON.parse(text);
    assert.equal(selected.evidenceFormat, 'grouped', text);
    assert.equal(selected.omittedEvidence, 0);
    assert.equal(selected.detailsOmitted, true);
    assert.deepEqual(selected.coverage, report.coverage);
    assert.deepEqual(selected.unknowns, report.unknowns);
    const expanded = selected.evidence.flatMap((group: any) => group.symbols.map(([name, span, explicitId]: string[]) => {
      const id = explicitId ?? (group.kind === 'file' ? group.path : `${group.path}#${name}`);
      return { id, path: group.path, kind: group.kind, role: group.role, depth: group.depth, name, span,
        ...(group.via ? { via: { source: id, ...group.via } } : {}) };
    }));
    assert.deepEqual(expanded, report.evidence.map(({ excerpt, excerptComplete, ...identity }) => identity));
    assert.equal(JSON.stringify(report), before);
    assert.ok(economyTokens(text) <= 1200);
    const recovered = await new Economy(f.root).read(selected.handle, { budget: null, raw: true });
    assert.equal(recovered.text, before);
  } finally { f.close(); }
});


test('automatic refresh opt-out prevents new investigation indexing', async () => {
  const f = fixture(); const previous = process.env.JULIUS_NO_REFRESH;
  try {
    process.env.JULIUS_NO_REFRESH = '1';
    await assert.rejects(runInvestigation(f.root, request), /refresh is disabled/);
  } finally {
    if (previous === undefined) delete process.env.JULIUS_NO_REFRESH; else process.env.JULIUS_NO_REFRESH = previous;
    f.close();
  }
});
