import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

const probe = `
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { keyFromRemote } from './src/notes/home.ts';
import { grepGraph } from './src/search/grep.ts';
if (process.argv[1] === 'remote') {
  const padding = '-'.repeat(200000);
  assert.equal(keyFromRemote('https://github.com/a' + padding + 'b/repo'), 'github.com/a' + padding + 'b/repo');
} else {
  const root = mkdtempSync(join(tmpdir(), 'julius-regex-'));
  try {
    writeFileSync(join(root, 'a.ts'), 'a'.repeat(10000) + '!');
    const graph = { meta: { version: 1, nodeCount: 1, edgeCount: 0, languages: [] }, nodes: [{ id: 'a.ts', kind: 'file', path: 'a.ts' }], edges: [] };
    assert.throws(() => grepGraph(graph, root, '(a+)+$'), /Search pattern exceeded/);
  } finally { rmSync(root, { recursive: true, force: true }); }
}
`;

for (const mode of ['remote', 'grep']) {
  test(`${mode}: adversarial input finishes within the child deadline`, () => {
    const result = spawnSync(process.execPath, ['--import', 'tsx', '--input-type=module', '-e', probe, mode], {
      encoding: 'utf8', timeout: 5000,
    });
    assert.equal(result.error, undefined, String(result.error));
    assert.equal(result.status, 0, result.stderr);
  });
}
