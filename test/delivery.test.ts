import { test } from 'node:test';
import assert from 'node:assert/strict';
import { selectDelivery, selectorLiterals } from '../src/economy/delivery.js';

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
