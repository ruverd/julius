import { test } from 'node:test';
import assert from 'node:assert/strict';
import { completeHeader, findLiterals, growSlice, selectDelivery, selectorLiterals, utf8SafeEnd } from '../src/economy/delivery.js';

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
