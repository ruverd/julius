import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const guard = 'data:text/javascript,' + encodeURIComponent(`
  export async function resolve(specifier, context, nextResolve) {
    if (specifier === 'openai' || specifier === '@anthropic-ai/sdk') {
      throw new Error('Structural startup loaded provider SDK: ' + specifier);
    }
    return nextResolve(specifier, context);
  }
`);

test('structural engine and MCP imports do not load provider SDKs', () => {
  for (const entry of ['../src/engine.ts', '../src/mcp/server.ts']) {
    const source = `await import(${JSON.stringify(new URL(entry, import.meta.url).href)});`;
    const result = spawnSync(process.execPath, ['--import', 'tsx', '--experimental-loader', guard, '--input-type=module', '--eval', source], { encoding: 'utf8', timeout: 30_000 });
    assert.equal(result.status, 0, result.stderr);
  }
});

test('CLI version command does not load provider SDKs', () => {
  const home = mkdtempSync(join(tmpdir(), 'julius-cold-start-'));
  try {
    const source = `process.argv = [process.execPath, 'julius', '--version']; await import(${JSON.stringify(new URL('../src/cli.ts', import.meta.url).href)});`;
    const result = spawnSync(process.execPath, ['--import', 'tsx', '--experimental-loader', guard, '--input-type=module', '--eval', source], {
      encoding: 'utf8', timeout: 30_000, env: { ...process.env, HOME: home, USERPROFILE: home, CI: '1', DO_NOT_TRACK: '1' },
    });
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /^\d+\.\d+\.\d+/);
  } finally { rmSync(home, { recursive: true, force: true }); }
});
