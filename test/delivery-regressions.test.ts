import { deliverInvestigation, type InvestigationReport } from '../src/investigation/index.js';
import { callCompact } from '../src/mcp/compact.js';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Economy, economyTokens } from '../src/economy/index.js';
import { scanLiterals, type DeliveryChoice } from '../src/economy/delivery.js';
function repo() { return mkdtempSync(join(tmpdir(), 'delivery-regression-')); }
function report(unindexedFiles: number, evidence: InvestigationReport['evidence']): InvestigationReport {
  return {
    version: 1, recipe: 'failure-localization', snapshot: 'snapshot', graphRevision: 'graph',
    coverage: { scope: 'repository source selection', indexedFiles: 1, sourceFiles: 3, unindexedFiles, traversalComplete: true },
    unknowns: ['kept unknown'], evidence, reused: false,
  };
}

test('an explicit complete budget leaves a contiguous next cursor', async () => {
  const root = repo();
  try {
    const body = 'ação🙂\r\n'.repeat(80);
    const choice: DeliveryChoice = { algorithm: 'full', label: 'complete', budget: 256, literals: [] };
    const economy = new Economy(root);
    const result = await economy.present(body, choice, 'mcp');
    const split = result.text.indexOf('\n');
    const header = JSON.parse(result.text.slice(0, split));
    assert.equal(header.incomplete, true);
    assert.equal(header.next.start, Buffer.byteLength(result.text.slice(split + 1)));
    const chunks = [result.text.slice(split + 1)];
    let start = header.next.start as number;
    let guard = 0;
    while (start < Buffer.byteLength(body)) {
      const read = await economy.read(header.handle, { start, budget: 256, transport: 'mcp' });
      chunks.push(read.bytes.toString('utf8'));
      const parsed = JSON.parse(read.text);
      assert.equal(parsed.start, start);
      start = parsed.next ? parsed.next.start : parsed.end;
      assert.ok(++guard < 20);
    }
    assert.equal(chunks.join(''), body);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('change-impact keeps dependent paths unless focus is explicitly requested', async () => {
  const root = repo();
  try {
    const { writeFileSync } = await import('node:fs');
    writeFileSync(join(root, 'core.ts'), 'export function hello() { return 1; }\n');
    writeFileSync(join(root, 'caller.ts'), 'import { hello } from "./core";\n' + Array.from({ length: 24 }, (_, i) => `export function caller${i}() { return hello(); }`).join('\n'));
    const result = await callCompact(root, 'julius_call', { operation: 'investigation.execute', args: { recipe: 'change-impact', paths: ['core.ts'], depth: 1 } });
    assert.equal(result.isError, false, result.text);
    const selected = JSON.parse(result.text);
    const dependents = selected.evidence.filter((item: { path: string; role: string }) => item.path === 'caller.ts' && item.role === 'dependent');
    const names = selected.evidenceFormat === 'grouped'
      ? dependents.flatMap((item: { symbols: string[][] }) => item.symbols.map(([name]: string[]) => name))
      : dependents.map((item: { name: string }) => item.name);
    assert.ok(Array.from({ length: 24 }, (_, i) => `caller${i}`).every(name => names.includes(name)), result.text);
    assert.equal(selected.omittedEvidence, 0);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('oversized investigation excerpts recover literals containing JSON escapes', async () => {
  const root = repo();
  try {
    const full = report(2, [{ id: 'a.ts#target', path: 'a.ts', span: 'L1-L3', name: 'target', kind: 'function', role: 'match', depth: 0,
      excerpt: 'prefix '.repeat(2000) + 'throw new Error("needle")' + ' suffix'.repeat(2000), excerptComplete: false }]);
    const selected = JSON.parse(await deliverInvestigation(root, full, { algorithm: 'targeted', label: 'targeted', budget: 400, literals: ['Error("needle")'] }));
    assert.equal(selected.match, true);
    assert.ok(selected.content.includes('Error(\\"needle\\")'));
    assert.ok(economyTokens(JSON.stringify(selected)) <= 400);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('a matching literal too large for its envelope is not reported absent', async () => {
  const root = repo();
  try {
    const focus = '🙂\n'.repeat(100);
    const result = await new Economy(root).present('prefix '.repeat(1000) + focus + 'suffix '.repeat(1000), { algorithm: 'targeted', label: 'targeted', budget: 256, literals: [focus] }, 'mcp');
    const parsed = JSON.parse(result.text);
    assert.equal(parsed.match, true);
    assert.equal(parsed.anchorOmitted, true);
    assert.equal(parsed.content, '');
    const recovered = await new Economy(root).read(parsed.handle, { start: parsed.next.start, budget: 1200, transport: 'mcp' });
    assert.ok(recovered.bytes.toString('utf8').includes(focus));
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('dense literal scans retain bounded offsets and exact counts', () => {
 const result = scanLiterals(Buffer.from('x'.repeat(100000)), ['x']);
 assert.equal(result.count, 100000);
 assert.equal(result.hits.length, 9);
});
