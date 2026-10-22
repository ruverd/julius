import assert from 'node:assert/strict';
import { test } from 'node:test';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import * as api from '../src/index.js';

test('package exposes the Julius executable and public engine', () => {
  const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
  assert.equal(pkg.name, '@ruverd/julius');
  assert.deepEqual(pkg.bin, { julius: 'dist/bin/julius.js' });
  assert.equal(typeof (api as Record<string, unknown>).Julius, 'function');
});

test('CLI help introduces Julius and the current command layout', () => {
  const home = mkdtempSync(join(tmpdir(), 'identity-home-'));
  try {
    const result = spawnSync(process.execPath, ['--import', 'tsx', 'src/cli.ts', '--help'], {
      encoding: 'utf8', env: { ...process.env, HOME: home, USERPROFILE: home },
    });
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /Usage: julius/);
    assert.match(result.stdout, /status/);
    assert.doesNotMatch(result.stdout, /\b(?:graft|trail)\b/i);
  } finally { rmSync(home, { recursive: true, force: true }); }
});
