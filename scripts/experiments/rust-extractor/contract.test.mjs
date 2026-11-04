import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const native = createRequire(import.meta.url)('./extractor.node');
test('native boundary rejects missing, non-string and unsupported-language arguments', () => {
  assert.throws(() => native.extract(), /Expected source and language strings/);
  assert.throws(() => native.extract(1, 'typescript'), /Expected string argument/);
  assert.throws(() => native.extract('', {}), /Expected string argument/);
  assert.throws(() => native.extract('', 'python'), /Pilot supports typescript and tsx only/);
  assert.deepEqual(JSON.parse(native.extract('', 'typescript')), [1, [], []]);
});
test('parser reuse across TS and TSX does not leak grammar, bindings or identifiers', () => {
  const ts = 'export class C { run() { return this.helper(); } helper() {} }';
  const tsx = 'export const View = () => <div>🦀</div>;';
  const reference = native.extract(ts, 'typescript');
  for (let i = 0; i < 100; i++) {
    native.extract(tsx, 'tsx');
    native.extract('const c = new Other(); c.run();', 'typescript');
    assert.equal(native.extract(ts, 'typescript'), reference);
  }
});
test('compact definition offsets address UTF-8 bytes after astral and accented text', () => {
  const source = '// 🦀 café\r\nexport function ação() { return "𐐀"; }\r\n';
  const [endRow, nodes, edges] = JSON.parse(native.extract(source, 'typescript'));
  assert.equal(endRow, 3);
  assert.equal(nodes.length, 1);
  const [, name, kind, start, end, header, firstRow, lastRow, exported] = nodes[0];
  const bytes = Buffer.from(source);
  assert.equal(name, 'ação'); assert.equal(kind, 'function'); assert.equal(exported, true);
  assert.equal(bytes.subarray(start, end).toString(), 'function ação() { return "𐐀"; }');
  assert.equal(bytes.subarray(start, header).toString(), 'function ação() ');
  assert.equal(firstRow, 2); assert.equal(lastRow, 2);
  assert.deepEqual(edges, [[-1, 'contains', 0, null, null, null]]);
});
