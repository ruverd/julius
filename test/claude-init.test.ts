import { test } from 'node:test';
import assert from 'node:assert/strict';

// The MCP launch command is resolved from PATH at init time; pin it to the npx
// form so these expectations are the same on every machine.
process.env.JULIUS_MCP_NPX = '1';
import { mkdtempSync, readFileSync, existsSync, writeFileSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { buildGraphIfMissing, runInit } from '../src/claude/init.js';
import { formatInitEpilogue } from '../src/cli-epilogue.js';
import { readStamp } from '../src/upkeep.js';

function fresh(): string { return mkdtempSync(join(tmpdir(), 'julius-init-')); }

function runPostinstall(env: Record<string, string>): string {
  try {
    return execFileSync(process.execPath, ['scripts/postinstall.mjs'],
      { encoding: 'utf8', env: { ...process.env, ...env } });
  } catch { return ''; }
}

test('CLI: --no-statusline leaves statusLine unset', () => {
  const d = fresh();
  const res = spawnSync(
    process.execPath,
    ['--import', 'tsx', 'src/cli.ts', 'init', d, '--no-build', '--no-agents', '--no-statusline', '--verbose'],
    { encoding: 'utf8' },
  );
  assert.equal(res.status, 0, res.stderr);
  assert.match(res.stderr, /skipped Claude Code statusLine/);
  const s = JSON.parse(readFileSync(join(d, '.claude', 'settings.json'), 'utf8'));
  assert.equal(s.statusLine, undefined);
  assert.equal(s.subagentStatusLine, undefined);
  assert.equal(readStamp(d)?.opts?.statusline, false);
});

test('formatInitEpilogue: graph built shows stats, wordmark, and the 3-step list', () => {
  const out = formatInitEpilogue({ graphBuilt: true, nodes: 6398, edges: 10912 });
  assert.match(out, /JULIUS/);
  assert.ok(out.includes('6,398 nodes · 10,912 edges'));
  assert.ok(out.includes('1. restart your agent'));
  assert.ok(out.includes('2. code as usual'));
  assert.ok(out.includes('3. explore by hand'));
  assert.ok(out.includes('julius ask'));
  assert.ok(!out.includes('build the graph'));
  assert.ok(!out.includes('OPENROUTER'));
  // julius/ is git-ignored now — the shareable artifact is .claude (wiring), not the graph.
  assert.ok(out.includes('git add .claude'));
});

test('formatInitEpilogue: graph not built shows "build the graph" as step 1, no stats, same column alignment', () => {
  const built = formatInitEpilogue({ graphBuilt: true, nodes: 4, edges: 4 });
  const notBuilt = formatInitEpilogue({ graphBuilt: false });
  assert.ok(notBuilt.includes('1. build the graph'));
  assert.ok(notBuilt.includes('2. restart your agent'));
  assert.ok(notBuilt.includes('3. code as usual'));
  assert.ok(notBuilt.includes('4. explore by hand'));
  assert.ok(!notBuilt.includes('nodes ·'));
  assert.ok(notBuilt.includes('git add .claude'));
  // the command column (after "restart your agent", the longest label) lines up
  // identically whether there are 3 or 4 numbered steps.
  const col = (text: string, marker: string) => text.split('\n').find((l) => l.includes(marker))!.indexOf('a new session');
  assert.equal(col(built, 'restart your agent'), col(notBuilt, 'restart your agent'));
});

test('CLI: julius init --verbose epilogue has the wordmark + next steps, and never mentions OPENROUTER', () => {
  const d = fresh();
  const res = spawnSync(
    process.execPath,
    ['--import', 'tsx', 'src/cli.ts', 'init', d, '--no-build', '--no-agents', '--verbose'],
    { encoding: 'utf8' },
  );
  assert.equal(res.status, 0, res.stderr);
  assert.ok(res.stderr.includes('JULIUS'), 'wordmark present');
  assert.ok(res.stderr.includes('code as usual'));
  assert.ok(res.stderr.includes('restart your agent'));
  assert.ok(res.stderr.includes('git add .claude'));
  assert.ok(res.stderr.includes('julius ask'));
  assert.ok(!res.stderr.includes('OPENROUTER'));
  // --no-build, never built before → "build the graph" is step 1
  assert.ok(res.stderr.includes('1. build the graph'));
});

// --- buildGraphIfMissing --------------------------------------------------
// Shared with the CLI's non-Claude path, so its guards are pinned here.

test('buildGraphIfMissing: build:false never spawns a build', () => {
  assert.equal(buildGraphIfMissing(fresh(), { build: false, cliPath: '/nonexistent/cli.js' }), false);
});

test('buildGraphIfMissing: no cliPath means nothing to spawn', () => {
  assert.equal(buildGraphIfMissing(fresh(), { build: true }), false);
});

test('buildGraphIfMissing: an existing graph is left alone', () => {
  const dir = fresh();
  mkdirSync(join(dir, '.julius', 'cache', '.graph'), { recursive: true });
  writeFileSync(join(dir, '.julius', 'cache', '.graph', 'wiring.json'), '{}');
  // A bogus cliPath would throw if it were reached; the wiring check short-circuits.
  assert.equal(buildGraphIfMissing(dir, { build: true, cliPath: '/nonexistent/cli.js' }), false);
});

test('runInit writes shared hooks and personal settings, with a user-level skill', () => {
  const repo = fresh(), home = fresh();
  const result = runInit(repo, { build: false, home });
  assert.ok(existsSync(join(repo, '.julius', 'hook.cjs')));
  assert.ok(existsSync(join(repo, '.julius', 'statusline.cjs')));
  assert.equal(result.skill, join(home, '.claude', 'skills', 'julius', 'SKILL.md'));
  assert.match(readFileSync(result.skill, 'utf8'), /name: julius/);
  const settings = JSON.parse(readFileSync(join(repo, '.claude', 'settings.json'), 'utf8'));
  assert.deepEqual(Object.keys(settings.hooks), ['SessionStart']);
  assert.equal(existsSync(join(repo, '.mcp.json')), false);
  assert.equal(result.built, false);
});

test('runInit is idempotent and preserves user-owned personal settings', () => {
  const repo = fresh(), home = fresh();
  mkdirSync(join(repo, '.claude'), { recursive: true });
  const file = join(repo, '.claude', 'settings.local.json');
  writeFileSync(file, JSON.stringify({ model: 'custom', statusLine: { command: 'mine' }, permissions: { allow: ['Bash(ls)'] } }));
  const first = runInit(repo, { build: false, global: false, home });
  const before = readFileSync(file, 'utf8');
  const settings = JSON.parse(before);
  assert.equal(settings.model, 'custom');
  assert.equal(settings.statusLine.command, 'mine');
  assert.ok(settings.permissions.allow.includes('Bash(ls)'));
  assert.equal(first.warnings.length, 1);
  runInit(repo, { build: false, global: false, home });
  assert.equal(readFileSync(file, 'utf8'), before);
});

test('runInit refreshes a stale global skill and honors no-statusline', () => {
  const repo = fresh(), home = fresh();
  const skill = join(home, '.claude', 'skills', 'julius', 'SKILL.md');
  mkdirSync(join(home, '.claude', 'skills', 'julius'), { recursive: true });
  writeFileSync(skill, 'stale');
  runInit(repo, { build: false, statusline: false, home });
  assert.match(readFileSync(skill, 'utf8'), /name: julius/);
  const settings = JSON.parse(readFileSync(join(repo, '.claude', 'settings.local.json'), 'utf8'));
  assert.equal(settings.statusLine, undefined);
  const pkg = JSON.parse(readFileSync('package.json', 'utf8'));
  assert.equal(pkg.scripts.postinstall, undefined, 'installation has no background side effects');
});
