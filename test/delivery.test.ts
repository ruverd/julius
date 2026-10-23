import { deliverInvestigation, type InvestigationReport } from '../src/investigation/index.js';
import { callCompact, COMPACT_INSTRUCTIONS } from '../src/mcp/compact.js';
import { INVESTIGATION_WORKFLOW } from '../src/hosts/investigation-instructions.js';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Economy, economyTokens } from '../src/economy/index.js';
import { completeHeader, findLiterals, growSlice, selectDelivery, selectorLiterals, utf8SafeEnd, type DeliveryChoice } from '../src/economy/delivery.js';

test('selector literals keep precedence and do not fall through', () => {
  assert.deepEqual(selectorLiterals('NEEDLE', { query: 'other', paths: ['a.ts'] }), ['NEEDLE']);
  assert.deepEqual(selectorLiterals(undefined, { query: 'missing', paths: ['a.ts'] }), ['missing']);
  assert.deepEqual(selectorLiterals(undefined, { pattern: 'pat' }), ['pat']);
  assert.deepEqual(selectorLiterals(undefined, { symbol: 'hello' }), ['hello']);
  assert.deepEqual(selectorLiterals(undefined, { file: 'src/a.ts' }), ['src/a.ts']);
  assert.deepEqual(selectorLiterals(undefined, { path: 'src/a.ts' }), ['src/a.ts']);
  assert.deepEqual(selectorLiterals(undefined, { paths: ['src/a.ts', 'src/b.ts'] }), ['src/a.ts', 'src/b.ts']);
  assert.deepEqual(selectorLiterals(undefined, { in: 'src', depth: 2, limit: 10, max_dirs: 4, content: 'body', recipe: 'change-impact' }), []);
});

test('selectDelivery distinguishes omitted budget from an explicit cap', () => {
  assert.deepEqual(selectDelivery({ delivery: 'complete', focus: 'NEEDLE', args: { query: 'q' } }), {
    algorithm: 'full', label: 'complete', budget: null, literals: [],
  });
  assert.deepEqual(selectDelivery({ delivery: 'complete', budget: 1200, args: {} }), {
    algorithm: 'full', label: 'complete', budget: 1200, literals: [],
  });
  assert.deepEqual(selectDelivery({ delivery: 'selective', args: {} }), {
    algorithm: 'fixed', label: 'targeted', budget: 1200, literals: [],
  });
  assert.deepEqual(selectDelivery({ args: { symbol: 'hello' } }), {
    algorithm: 'targeted', label: 'targeted', budget: 1200, literals: ['hello'],
  });
  assert.deepEqual(selectDelivery({ focus: 'NEEDLE', budget: 400, args: {} }), {
    algorithm: 'targeted', label: 'targeted', budget: 400, literals: ['NEEDLE'],
  });
  assert.deepEqual(selectDelivery({ args: { in: 'src' } }), {
    algorithm: 'fixed', label: 'fixed', budget: 1200, literals: [],
  });
  assert.throws(() => selectDelivery({ delivery: 'fixed', args: {} }), /delivery must be selective or complete/);
});

test('utf-8 truncation lands on code point boundaries', () => {
  const bytes = Buffer.from('ação🙂');
  assert.equal(utf8SafeEnd(bytes, 0), 0);
  assert.equal(utf8SafeEnd(bytes, 1), 1);
  assert.equal(utf8SafeEnd(bytes, 2), 1);
  assert.equal(utf8SafeEnd(bytes, 3), 3);
  assert.equal(utf8SafeEnd(bytes, bytes.length), bytes.length);
});

test('literal search is non-overlapping and path order breaks ties', () => {
  const bytes = Buffer.from('alpha alpha beta');
  assert.deepEqual(findLiterals(bytes, ['alpha']), [{ start: 0, end: 5 }, { start: 6, end: 11 }]);
  const tie = Buffer.from('ab');
  assert.deepEqual(findLiterals(tie, ['b', 'ab']), [{ start: 0, end: 2 }]);
});

test('window growth keeps the anchor and stops when the callback rejects', () => {
  const bytes = Buffer.from('head\nTARGET\ntail');
  const anchor = findLiterals(bytes, ['TARGET'])[0]!;
  const wide = growSlice(bytes, anchor.start, anchor.end, () => true);
  assert.deepEqual(wide, { start: 0, end: bytes.length });
  const tight = growSlice(bytes, anchor.start, anchor.end, (start, end) => end - start <= 'TARGET'.length);
  assert.deepEqual(tight, { start: anchor.start, end: anchor.end });
  assert.equal(growSlice(bytes, anchor.start, anchor.end, () => false), null);
});

test('complete header is one JSON line with stable keys', () => {
  assert.equal(completeHeader({
    handle: 'sha256:' + 'a'.repeat(64), totalBytes: 4, omittedBytes: 0, incomplete: false, next: null, format: 'utf8',
  }), '{"delivery":"complete","handle":"sha256:' + 'a'.repeat(64) + '","totalBytes":4,"omittedBytes":0,"incomplete":false,"next":null,"format":"utf8"}');
});

function repo(): string {
  return mkdtempSync(join(tmpdir(), 'delivery-'));
}

test('full delivery writes a header and the verbatim body', async () => {
  const root = repo();
  try {
    const body = 'ação🙂\r\nretry_limit=7';
    const choice: DeliveryChoice = { algorithm: 'full', label: 'complete', budget: null, literals: [] };
    const result = await new Economy(root).present(body, choice, 'mcp');
    const split = result.text.indexOf('\n');
    const header = JSON.parse(result.text.slice(0, split));
    assert.equal(result.text.slice(split + 1), body);
    assert.equal(header.delivery, 'complete');
    assert.equal(header.incomplete, false);
    assert.equal(header.next, null);
    assert.equal(header.handle, result.handle);
    const raw = await new Economy(root).read(header.handle, { budget: 16000, raw: true });
    assert.equal(raw.bytes.toString('utf8'), body);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

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

test('targeted delivery windows the literal and a miss copies no head', async () => {
  const root = repo();
  try {
    const body = `${'head '.repeat(800)}\nTARGET retry_limit=7\n${'tail '.repeat(800)}`;
    const economy = new Economy(root);
    const hit = await economy.present(body, { algorithm: 'targeted', label: 'targeted', budget: 300, literals: ['retry_limit=7'] }, 'mcp');
    const hitBody = JSON.parse(hit.text);
    assert.equal(hitBody.match, true);
    assert.match(hitBody.content, /retry_limit=7/);
    assert.ok(economyTokens(hit.text) <= 300);
    assert.ok(hitBody.offsets.length <= 8);
    const miss = await economy.present(body, { algorithm: 'targeted', label: 'targeted', budget: 1200, literals: ['BENCH_MARKER_MISSING'] }, 'mcp');
    const missBody = JSON.parse(miss.text);
    assert.equal(missBody.match, false);
    assert.equal(missBody.content, '');
    assert.equal(miss.text.includes('head '), false);
    assert.deepEqual(missBody.next, { start: 0, end: Buffer.byteLength(body) });
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('fixed delivery keeps the head and omits a tail fact', async () => {
  const root = repo();
  try {
    const body = `${'word '.repeat(2000)}\nBENCH_MARKER_078: retry_limit=7`;
    const result = await new Economy(root).present(body, { algorithm: 'fixed', label: 'fixed', budget: 1200, literals: [] }, 'mcp');
    assert.equal(result.text.includes('BENCH_MARKER_078'), false);
    const parsed = JSON.parse(result.text);
    assert.equal(parsed.delivery, 'fixed');
    assert.ok(parsed.next.start > 0);
    assert.ok(economyTokens(result.text) <= 1200);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('an uncountable full body stores bytes and records null tokens', async () => {
  const root = repo();
  try {
    const body = 'a'.repeat(4097);
    const economy = new Economy(root);
    const result = await economy.present(body, { algorithm: 'full', label: 'complete', budget: null, literals: [] }, 'mcp');
    assert.equal(result.text.includes('\n'), false);
    const header = JSON.parse(result.text);
    assert.equal(header.incomplete, true);
    assert.deepEqual(header.next, { start: 0, end: body.length });
    const stats = await economy.stats();
    assert.equal(stats.rawTokens, null);
    assert.equal(stats.deliveredTokens, null);
    assert.equal((await economy.read(header.handle, { budget: 16000, raw: true })).bytes.toString('utf8'), body);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('compact calls window a focus and return a complete body verbatim', async () => {
  const root = repo();
  try {
    const content = `${'word '.repeat(2000)}\nBENCH_MARKER_078: retry_limit=7`;
    const fixed = await callCompact(root, 'julius_call', { operation: 'context.capture', args: { content } });
    assert.equal(fixed.isError, false, fixed.text);
    assert.equal(fixed.text.includes('BENCH_MARKER_078'), false);
    const focused = await callCompact(root, 'julius_call', { operation: 'context.capture', args: { content }, focus: 'BENCH_MARKER_078: retry_limit=7' });
    assert.equal(focused.isError, false, focused.text);
    assert.match(focused.text, /retry_limit=7/);
    assert.ok(economyTokens(focused.text) <= 1200);
    const complete = await callCompact(root, 'julius_call', { operation: 'context.capture', args: { content }, delivery: 'complete' });
    assert.equal(complete.text.slice(complete.text.indexOf('\n') + 1), content);
    const capped = await callCompact(root, 'julius_call', { operation: 'context.capture', args: { content }, delivery: 'complete', budget: 256 });
    const header = JSON.parse(capped.text.slice(0, capped.text.indexOf('\n')));
    assert.equal(header.incomplete, true);
    assert.ok(header.next);
    const bad = await callCompact(root, 'julius_call', { operation: 'context.capture', args: { content }, delivery: 'fixed' });
    assert.equal(bad.isError, true);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

function report(unindexedFiles: number, evidence: InvestigationReport['evidence']): InvestigationReport {
  return {
    version: 1, recipe: 'failure-localization', snapshot: 'snapshot', graphRevision: 'graph',
    coverage: { scope: 'repository source selection', indexedFiles: 1, sourceFiles: 3, unindexedFiles, traversalComplete: true },
    unknowns: ['kept unknown'], evidence, reused: false,
  };
}

test('investigation delivery keeps coverage and withholds unmatched evidence', async () => {
  const root = repo();
  try {
    const evidence = Array.from({ length: 20 }, (_, index) => ({
      id: `a.ts#fn${index}`, path: 'a.ts', span: 'L1-L2', kind: 'function', name: `fn${index}`,
      role: 'dependent' as const, depth: 1, excerpt: `excerpt ${index} ${'pad '.repeat(40)}`, excerptComplete: true,
    }));
    evidence.push({ id: 'b.ts#target', path: 'b.ts', span: 'L3-L4', kind: 'function', name: 'target', role: 'match', depth: 0, excerpt: 'BENCH_MARKER_078: retry_limit=7', excerptComplete: true });
    const full = report(2, evidence);
    const selected = JSON.parse(await deliverInvestigation(root, full, { algorithm: 'targeted', label: 'targeted', budget: 1200, literals: ['BENCH_MARKER_078'] }));
    assert.equal(selected.coverage.unindexedFiles, 2);
    assert.deepEqual(selected.unknowns, ['kept unknown']);
    assert.ok(selected.evidence.every((item: { excerpt: string }) => item.excerpt.includes('BENCH_MARKER_078')));
    assert.equal(selected.evidence.some((item: { path: string }) => item.path === 'vendor/readme.txt'), false);
    const missed = JSON.parse(await deliverInvestigation(root, full, { algorithm: 'targeted', label: 'targeted', budget: 1200, literals: ['BENCH_MARKER_MISSING'] }));
    assert.equal(missed.match, false);
    assert.deepEqual(missed.evidence, []);
    assert.equal(missed.omittedEvidence, evidence.length);
    assert.equal(missed.coverage.unindexedFiles, 2);
    const huge = report(2, [{ id: 'b.ts#target', path: 'b.ts', span: 'L3-L4', kind: 'function', name: 'target', role: 'match', depth: 0, excerpt: `${'pad '.repeat(2000)} BENCH_MARKER_078: retry_limit=7`, excerptComplete: false }]);
    const narrowed = await deliverInvestigation(root, huge, { algorithm: 'targeted', label: 'targeted', budget: 400, literals: ['retry_limit=7'] });
    assert.match(narrowed, /retry_limit=7/);
    assert.ok(economyTokens(narrowed) <= 400);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('agent instructions name delivery, focus, next, and commandless use', () => {
  for (const text of [COMPACT_INSTRUCTIONS, INVESTIGATION_WORKFLOW]) {
    assert.match(text, /delivery complete/);
    assert.match(text, /focus/);
    assert.match(text, /next\.start/);
    assert.match(text, /match false/);
    assert.match(text, /never ask the user to run Julius commands/);
  }
});

test('window growth over a large body is bounded and stays within budget', async () => {
  const root = repo();
  try {
    const lines = Array.from({ length: 20000 }, (_, index) => `line ${index} ok`);
    lines[10000] = 'MIDDLE_LITERAL_QX retry_limit=7';
    const body = lines.join('\n');
    const started = Date.now();
    const result = await new Economy(root).present(body, { algorithm: 'targeted', label: 'targeted', budget: 16000, literals: ['MIDDLE_LITERAL_QX'] }, 'mcp');
    assert.ok(Date.now() - started < 10000);
    assert.ok(economyTokens(result.text) <= 16000);
    const parsed = JSON.parse(result.text);
    assert.equal(parsed.match, true);
    assert.equal(parsed.content, 'MIDDLE_LITERAL_QX retry_limit=7');
    assert.equal(parsed.content.includes('line 0 ok'), false);
    assert.equal(parsed.content.includes('line 19999 ok'), false);
    assert.deepEqual(parsed.hits, [{ line: 10001, text: 'MIDDLE_LITERAL_QX retry_limit=7' }]);
    assert.equal(parsed.next, undefined);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('a long matching line keeps the literal inside 160 characters', async () => {
  const root = repo();
  try {
    const line = `${'pad '.repeat(2000)}retry_limit=7${' tail'.repeat(200)}`;
    const body = `before\n${line}\nafter`;
    const parsed = JSON.parse((await new Economy(root).present(body, { algorithm: 'targeted', label: 'targeted', budget: 400, literals: ['retry_limit=7'] }, 'mcp')).text);
    assert.match(parsed.content, /retry_limit=7/);
    assert.equal(parsed.content.includes('before'), false);
    assert.equal(parsed.content.includes('after'), false);
    assert.equal(parsed.hits[0].line, 2);
    assert.ok(parsed.hits[0].text.length <= 160);
    assert.ok(economyTokens(JSON.stringify(parsed)) <= 400);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('a body that fits the budget is returned whole even when the literal is absent', async () => {
  const root = repo();
  try {
    const economy = new Economy(root);
    const short = 'a short body without the focus';
    const kept = await economy.present(short, { algorithm: 'targeted', label: 'targeted', budget: 1200, literals: ['MISSING_FOCUS'] }, 'mcp');
    assert.equal(kept.text, short);
    assert.equal(kept.handle, null);
    const large = `${'word '.repeat(4000)}end`;
    const missed = JSON.parse((await economy.present(large, { algorithm: 'targeted', label: 'targeted', budget: 1200, literals: ['MISSING_FOCUS'] }, 'mcp')).text);
    assert.equal(missed.match, false);
    assert.equal(missed.matchCount, 0);
    assert.equal(missed.content, '');
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('a complete-fit investigation report keeps evidence without the literal', async () => {
  const root = repo();
  try {
    const small = report(0, [{ id: 'a.ts#only', path: 'a.ts', span: 'L1-L2', kind: 'function', name: 'only', role: 'dependent', depth: 1, excerpt: 'unrelated excerpt', excerptComplete: true }]);
    const delivered = JSON.parse(await deliverInvestigation(root, small, { algorithm: 'targeted', label: 'targeted', budget: 1200, literals: ['BENCH_MARKER_MISSING'] }));
    assert.equal(delivered.evidence.length, 1);
    assert.equal(delivered.evidence[0].excerpt, 'unrelated excerpt');
    assert.equal(delivered.omittedEvidence, 0);
    assert.equal(delivered.match, undefined);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('complete context recovery returns only the requested bytes and honors explicit budgets', async () => {
  const root = repo();
  try {
    const content = 'ação🙂\r\n"quoted"\\path '.repeat(500);
    const initial = await callCompact(root, 'julius_call', { operation: 'context.capture', args: { content }, budget: 400 });
    assert.equal(initial.isError, false, initial.text);
    const preview = JSON.parse(initial.text);
    const recovered = await callCompact(root, 'julius_call', { operation: 'context.read', args: { handle: preview.handle, start: preview.end }, delivery: 'complete' });
    assert.equal(recovered.isError, false, recovered.text);
    const split = recovered.text.indexOf('\n');
    const header = JSON.parse(recovered.text.slice(0, split));
    assert.equal(header.start, preview.end);
    assert.equal(header.end, Buffer.byteLength(content));
    assert.equal(header.handle, preview.handle);
    assert.deepEqual(Buffer.concat([Buffer.from(preview.content), Buffer.from(recovered.text.slice(split + 1))]), Buffer.from(content));
    const capped = await callCompact(root, 'julius_call', { operation: 'context.read', args: { handle: preview.handle, start: preview.end }, delivery: 'complete', budget: 400 });
    assert.equal(capped.isError, false, capped.text);
    assert.ok(economyTokens(capped.text) <= 400);
    assert.ok(JSON.parse(capped.text).end < header.end);
    const ranged = await callCompact(root, 'julius_call', { operation: 'context.read', args: { handle: preview.handle, start: 2, end: 7 }, delivery: 'complete' });
    const rangeSplit = ranged.text.indexOf('\n');
    const rangeHeader = JSON.parse(ranged.text.slice(0, rangeSplit));
    assert.equal(rangeHeader.format, 'base64');
    assert.deepEqual(Buffer.from(ranged.text.slice(rangeSplit + 1), 'base64'), Buffer.from(content).subarray(2, 7));
  } finally { rmSync(root, { recursive: true, force: true }); }
});
