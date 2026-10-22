/** Julius host wiring uses one identity and remains idempotent. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

// Pin the MCP launch command to the npx form, whatever this machine has installed.
process.env.JULIUS_MCP_NPX = '1';
process.env.JULIUS_NO_FETCH = '1';
delete process.env.JULIUS_NO_JULIUS_SWITCH;

import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { delimiter, join, relative } from 'node:path';
import { spawnSync } from 'node:child_process';
import { runHostsInit } from '../src/hosts/init.js';
import { HOSTS, hostRelPath, hostWiringName } from '../src/hosts/registry.js';
import { instructionBody, cursorRule } from '../src/hosts/instructions.js';
import { juliusSpelling } from '../src/claude/skill-template.js';
import { JULIUS_MARKERS, fencedBlock, upsertSection } from '../src/hosts/sections.js';
import { registerMcpConfigs } from '../src/hosts/mcp-config.js';
import { changed, runRetract } from '../src/hosts/retract.js';
import { runInit } from '../src/claude/init.js';
import { runUpkeep } from '../src/upkeep-run.js';
import { readStamp, runningVersion, wiredHostIds } from '../src/upkeep.js';
import { BRAND_ENV } from '../src/brand.js';
import { tmpRepo } from './helpers.js';

const ALL = HOSTS.map((h) => h.id);
/** A julius command an agent would be told to run. `julius/` (the code map's folder) is not one. */
const JULIUS_COMMAND = /\bjulius (ask|grep|callers|skeleton|map|build|check|stats|note|mcp)\b/;

/** Every file under `dir`, repo-relative, skipping the graph and git. */
function filesUnder(dir: string): string[] {
  const out: string[] = [];
  const walk = (d: string) => {
    for (const e of readdirSync(d, { withFileTypes: true })) {
      if (e.name === '.git') continue;
      const p = join(d, e.name);
      if (e.isDirectory()) walk(p);
      else out.push(relative(dir, p));
    }
  };
  walk(dir);
  return out.sort();
}

/** A scratch home where every agent with a machine-wide config is installed. */
function agentHome(): string {
  const home = tmpRepo('julius-hosts-home');
  for (const d of [['.codex'], ['.config', 'opencode'], ['.gemini', 'config']]) mkdirSync(join(home, ...d), { recursive: true });
  return home;
}

test('julius init for every agent: julius-named files, julius commands, a julius server', () => {
  const home = agentHome();
  const repo = tmpRepo('julius-hosts');
  const r = runHostsInit(repo, { all: true, home, brand: 'julius' });
  assert.equal(r.written.length, ALL.length);

  const files = filesUnder(repo);
  assert.deepEqual(files.filter((f) => /\b(?:graft|trail)\b/.test(f)), [], `no upstream-branded file in the repo: ${files.join(', ')}`);
  for (const rel of [
    join('.cursor', 'rules', 'julius.mdc'),
    join('.cursor', 'hooks', 'julius-hooks.cjs'),
    join('.kiro', 'steering', 'julius.md'),
    join('.windsurf', 'rules', 'julius.md'),
    join('.adal', 'skills', 'julius', 'SKILL.md'),
    join('.grok', 'skills', 'julius', 'SKILL.md'),
  ]) assert.ok(files.includes(rel), `${rel} written`);

  // Every instruction file names a supported Julius command.
  for (const host of HOSTS) {
    const text = readFileSync(join(repo, hostRelPath(host, 'julius')), 'utf8');
    assert.match(text, JULIUS_COMMAND, `${host.id} names a julius command`);
    assert.match(text, /\bjulius (ask|grep)\b/, `${host.id} names julius's`);
  }
  const agents = readFileSync(join(repo, 'AGENTS.md'), 'utf8');
  assert.equal(agents.split(JULIUS_MARKERS.start).length - 1, 1, 'one block, shared by three hosts');
  
  assert.match(readFileSync(join(repo, '.adal', 'skills', 'julius', 'SKILL.md'), 'utf8'), /^---\nname: julius\n/);

  // The MCP server is julius's, under julius's name, in every config.
  const npx = { command: 'npx', args: ['-y', '@ruverd/julius', 'mcp'] };
  for (const rel of [join('.cursor', 'mcp.json'), join('.gemini', 'settings.json'), join('.kiro', 'settings', 'mcp.json')]) {
    assert.deepEqual(JSON.parse(readFileSync(join(repo, rel), 'utf8')).mcpServers, { julius: npx }, rel);
  }
  assert.deepEqual(JSON.parse(readFileSync(join(repo, 'opencode.json'), 'utf8')).mcp, { julius: { type: 'local', command: ['npx', '-y', '@ruverd/julius', 'mcp'], enabled: true } });
  assert.deepEqual(JSON.parse(readFileSync(join(home, '.gemini', 'config', 'mcp_config.json'), 'utf8')).mcpServers, { julius: npx });
  for (const toml of [join(repo, '.grok', 'config.toml'), join(home, '.codex', 'config.toml')]) {
    assert.equal(readFileSync(toml, 'utf8'), '[mcp_servers.julius]\ncommand = "npx"\nargs = ["-y", "@ruverd/julius", "mcp"]\n', toml);
  }
  assert.ok(existsSync(join(home, '.gemini', 'skills', 'julius', 'SKILL.md')));
  
  const hooks = JSON.parse(readFileSync(join(repo, '.cursor', 'hooks.json'), 'utf8'));
  assert.match(hooks.hooks.postToolUse[0].command, /julius-hooks\.cjs" cursor-post-tool$/);

  // A teammate on julius refreshing the same repo writes the same files: it never flips back.
  assert.equal(hostWiringName(repo), 'julius');
  const again = runHostsInit(repo, { all: true, home });
  assert.ok(again.written.every((w) => w.action === 'unchanged'), JSON.stringify(again.written));
  assert.ok(again.mcp.every((w) => w.action === 'unchanged'), JSON.stringify(again.mcp));
});

test('CLI: julius init --dry-run names julius\'s files', () => {
  const repo = tmpRepo('julius-dry');
  const home = tmpRepo('julius-dry-home');
  const r = spawnSync(process.execPath, ['--import', 'tsx', join('src', 'bin', 'julius.ts'), 'init', repo, '--no-build', '--agents', 'cursor', 'kiro', 'adal', '--dry-run'], {
    encoding: 'utf8',
    env: { ...process.env, HOME: home, USERPROFILE: home, DO_NOT_TRACK: '1', JULIUS_INVOKED_AS: undefined, JULIUS_HOME: undefined },
  });
  assert.equal(r.status, 0, r.stderr);
  for (const rel of [join('.cursor', 'rules', 'julius.mdc'), join('.kiro', 'steering', 'julius.md'), join('.adal', 'skills', 'julius', 'SKILL.md')]) {
    assert.ok(r.stderr.includes(rel), `${rel} in ${r.stderr}`);
  }
  assert.doesNotMatch(r.stderr, /graft\.mdc|steering[\\/]trail\.md/);
  assert.deepEqual(readdirSync(repo), [], 'a dry run writes nothing');
});
