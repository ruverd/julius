import { test } from 'node:test';
import assert from 'node:assert/strict';
import childProcess from 'node:child_process';
import { syncBuiltinESMExports } from 'node:module';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runInvestigation } from '../src/investigation/index.js';

test('warm investigations share source/config enumeration while retaining freshness verification', async () => {
  const root = mkdtempSync(join(tmpdir(), 'investigation-enumeration-'));
  const original = childProcess.spawnSync;
  try {
    writeFileSync(join(root, 'core.ts'), 'export function hello() { return 1; }\n');
    const args = { recipe: 'change-impact' as const, paths: ['core.ts'], depth: 1 };
    await runInvestigation(root, args);
    let enumerations = 0;
    childProcess.spawnSync = ((...args: Parameters<typeof original>) => {
      if (args[0] === 'git' && Array.isArray(args[1]) && args[1][0] === 'ls-files') enumerations++;
      return original(...args);
    }) as typeof original;
    syncBuiltinESMExports();
    const warm = await runInvestigation(root, args);
    assert.equal(warm.reused, true);
    assert.equal(enumerations, 2, 'one enumeration per before/after snapshot');
    writeFileSync(join(root, 'caller.ts'), 'import { hello } from "./core"; export function newCaller() { return hello(); }\n');
    const changed = await runInvestigation(root, args);
    assert.equal(changed.reused, false);
    assert.ok(changed.evidence.some(item => item.name === 'newCaller'));
  } finally {
    childProcess.spawnSync = original;
    syncBuiltinESMExports();
    rmSync(root, { recursive: true, force: true });
  }
});
