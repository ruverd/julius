import { mkdirSync, writeFileSync, readFileSync, chmodSync, rmSync, rmdirSync, existsSync, appendFileSync } from 'node:fs';
import { join, dirname, resolve, isAbsolute } from 'node:path';
import { homedir } from 'node:os';
import { execFileSync } from 'node:child_process';
import { disableJuliusServerIn, installClaudeGlobal, type GlobalWrite } from '../hosts/claude-global.js';
import { mergeJuliusSettings, mergeJuliusShared, mergeJuliusLocal } from './settings-merge.js';
import { statuslineShim, hooksShim, rememberInstall } from './shim-template.js';
import { skillTemplate } from './skill-template.js';
import { mergeJsonKey, serverEntry, type McpWrite } from '../hosts/mcp-config.js';
import { readJsonObject } from '../hosts/config-write.js';
import { ignoreInJuliusDir } from '../notes/repo-julius.js';
export { ignoreInJuliusDir };
import { hasJuliusIndex } from '../graph/root.js';
import type { PlannedWrite } from '../hosts/plan.js';
import { repoWiredForJulius, type Brand } from '../brand.js';

/** julius's committed hook, inside `.julius/` where a `.claude/*` ignore rule can't drop it. */
export const JULIUS_HOOK = join('.julius', 'hook.cjs');
/** The status line's shim. Also in `.julius/`, but ignored there: only people with julius draw it. */
export const JULIUS_STATUSLINE = join('.julius', 'statusline.cjs');
/** Where julius's skill goes: the user's own `~/.claude`, never the repo. */
export function juliusSkillPath(home: string = homedir()): string {
  return join(home, '.claude', 'skills', 'julius', 'SKILL.md');
}

/**
 * The files `runInit` writes — pure, no writes, so `--dry-run` and the picker
 * can report them up front.
 */
export function claudeTargets(dir: string, initBrand?: Brand, home?: string): PlannedWrite[] {
  return claudeTargetsFor(dir, wiringName(dir, initBrand), home);
}

/** The single identity used for Claude Code wiring. */
export function wiringName(dir: string, initBrand?: Brand): Brand {
  return 'julius';
}

/**
 * `claudeTargets` under one name.
 *
 * julius splits what it writes in two. Shared, committed once by whoever sets
 * the repo up: `.julius/hook.cjs` and one SessionStart entry in
 * `.claude/settings.json`, which is all a teammate without julius needs to be
 * shown the learnings and offered julius. Personal, where git never looks: the
 * status line and allowlist in `.claude/settings.local.json`, the skill in
 * `~/.claude/skills/`, and the other hooks in `~/.claude` (hosts/claude-global.ts).
 * No MCP server: the hooks and the `julius` command do what it did.
 */
export function claudeTargetsFor(dir: string, name: Brand, home: string = homedir()): PlannedWrite[] {
  const t = (path: string, what: string): PlannedWrite => ({ hostId: 'claude', id: 'claude', path, scope: 'repo', kind: 'claude', what });
  return [
    t(join(dir, '.claude', 'settings.json'), 'julius SessionStart hook, shared'),
    t(join(dir, JULIUS_HOOK), 'hooks shim, shared'),
    t(join(dir, '.claude', 'settings.local.json'), 'julius statusline + allowlist, yours'),
    t(join(dir, JULIUS_STATUSLINE), 'statusline shim, git-ignored'),
    { hostId: 'claude', id: 'claude', path: juliusSkillPath(home), scope: 'global', kind: 'claude', what: 'julius skill' },
  ];
}

/** Previous repo-local layout, retained for cleanup during refresh and uninstall. */
export function legacyClaudeTargets(dir: string, name: Brand): PlannedWrite[] {
  const t = (path: string, what: string, kind: PlannedWrite['kind'] = 'claude'): PlannedWrite =>
    ({ hostId: 'claude', id: 'claude', path, scope: 'repo', kind, what });
  return [
    t(join(dir, '.claude', 'settings.json'), `${name} statusline + hook blocks`),
    t(join(dir, '.claude', 'helpers', `${name}-statusline.cjs`), 'statusline shim'),
    t(join(dir, '.claude', 'helpers', `${name}-hooks.cjs`), 'hooks shim'),
    t(join(dir, '.claude', 'skills', name, 'SKILL.md'), `${name} skill`),
    // Tagged 'mcp' so the picker doesn't label Claude Code as having no MCP.
    t(join(dir, '.mcp.json'), `mcpServers.${name}`, 'mcp'),
  ];
}

/**
 * Build the graph if it isn't there yet. Not Claude-specific: the wiring for any
 * host points at `julius/`, so `julius init` builds whichever hosts were selected —
 * this lives beside `runInit` only because that's the caller that owns `built`.
 * Best-effort; the user can always run `julius build` (the epilogue says so).
 */
export function buildGraphIfMissing(dir: string, opts: { build?: boolean; cliPath?: string }): boolean {
  // `hasJuliusIndex`, not just wiring.json: a workspace parent's graph IS its
  // `workspace.json` (nodes live in the children), so testing for wiring.json
  // alone would call it unbuilt and rebuild every child on each init.
  if (opts.build === false || !opts.cliPath || hasJuliusIndex(dir)) return false;
  try {
    // execArgv carries the loader julius itself was started with (tsx, when run
    // from source), so the child can run a .ts entry point too.
    execFileSync(process.execPath, [...process.execArgv, opts.cliPath, 'build', '.'], { cwd: dir, stdio: 'inherit', timeout: 300000 });
    return true;
  } catch {
    return false;
  }
}

export interface InitResult {
  settingsPath: string;
  shims: string[];
  /** Where the skill went; '' when nothing was written (julius under `--no-global`). */
  skill: string;
  /** Reserved MCP write result; current Claude Code wiring uses hooks and returns null. */
  mcp: McpWrite | null;
  /** the user-level writes under `~/.claude`, empty when `global: false`. */
  global: GlobalWrite[];
  warnings: string[];
  built: boolean;
}

export function runInit(
  dir: string,
  opts: { build?: boolean; cliPath?: string; statusline?: boolean; global?: boolean; home?: string; brand?: Brand } = {},
): InitResult {
  return runJuliusInit(dir, opts);
}

function readSettings(path: string): Record<string, any> {
  try { return JSON.parse(readFileSync(path, 'utf8')); } catch { return {}; } // none/invalid → start fresh
}

/**
 * `runInit` for a repo on julius. Shared: `.julius/hook.cjs` and its one
 * SessionStart entry in `.claude/settings.json`. Personal: everything else.
 * Run again over a repo set up the old way, it moves it: the old shims, the
 * repo skill and julius's `.mcp.json` server go.
 */
function runJuliusInit(
  dir: string,
  opts: { build?: boolean; cliPath?: string; statusline?: boolean; global?: boolean; home?: string },
): InitResult {
  const home = opts.home ?? homedir();
  const global = opts.global !== false;
  const [settings, hook, local, statusline, skill] = claudeTargetsFor(dir, 'julius', home).map((t) => t.path);

  mkdirSync(dirname(hook), { recursive: true });
  writeFileSync(hook, hooksShim()); chmodSync(hook, 0o755);
  writeFileSync(statusline, statuslineShim()); chmodSync(statusline, 0o755);
  ignoreInJuliusDir(dir, 'statusline.cjs');
  rememberInstall(home);

  const shared = mergeJuliusShared(readSettings(settings));
  mkdirSync(dirname(settings), { recursive: true });
  writeFileSync(settings, `${JSON.stringify(shared, null, 2)}\n`);

  // Hooks for every other event come from `~/.claude`. Only when that's off do
  // they go in the personal file, beside the status line.
  const { merged, warnings } = mergeJuliusLocal(readSettings(local), { statusline: opts.statusline, hooks: !global });
  writeFileSync(local, `${JSON.stringify(merged, null, 2)}\n`);
  keepOutOfGit(dir, join('.claude', 'settings.local.json'));

  let skillPath = '';
  if (global) {
    mkdirSync(dirname(skill), { recursive: true });
    writeFileSync(skill, skillTemplate('julius'));
    skillPath = skill;
  }

  clearOldLayout(dir);

  const globalWrites = global ? installClaudeGlobal(home, 'julius') : [];
  // A julius repo on a machine with julius's server installed for everything:
  // julius goes off in this folder, so its tools don't show here.
  if (global) globalWrites.push(disableJuliusServerIn(home, resolve(dir)));

  const built = buildGraphIfMissing(dir, opts);
  return { settingsPath: settings, shims: [statusline, hook], skill: skillPath, mcp: null, global: globalWrites, warnings, built };
}

/**
 * What julius wrote before 0.23 and doesn't any more: the shims in
 * `.claude/helpers/`, the skill in `.claude/skills/`, and julius's server in
 * `.mcp.json`. Settings entries are already gone: the merges replace them.
 */
function clearOldLayout(dir: string): void {
  for (const n of ['julius'] as const) {
    const [, oldSl, oldHk, oldSkill] = legacyClaudeTargets(dir, n).map((t) => t.path);
    rmSync(oldSl, { force: true });
    rmSync(oldHk, { force: true });
    rmSync(dirname(oldSkill), { recursive: true, force: true });
  }
  // The folders they were in, once nothing else is: rmdir refuses a non-empty one.
  for (const d of [join(dir, '.claude', 'helpers'), join(dir, '.claude', 'skills')]) {
    try { rmdirSync(d); } catch { /* holds the user's files, or was never there */ }
  }
  dropServer(join(dir, '.mcp.json'), ['julius']);
}

/** Take julius's server out of an `.mcp.json`; the file goes if nothing else was in it. */
function dropServer(path: string, names: string[]): void {
  try {
    const loaded = readJsonObject(path);
    if (loaded === 'unparseable' || !loaded.existed) return;
    const root = loaded.root;
    const servers = root.mcpServers;
    if (!servers || typeof servers !== 'object' || !names.some((n) => n in servers)) return;
    for (const n of names) delete servers[n];
    if (Object.keys(servers).length === 0) delete root.mcpServers;
    if (Object.keys(root).length === 0) rmSync(path, { force: true });
    else writeFileSync(path, `${JSON.stringify(root, null, 2)}\n`);
  } catch { /* leave it as the user has it */ }
}

/**
 * Keep a personal file out of git without touching the repo's `.gitignore`:
 * if nothing ignores it already, it goes in `.git/info/exclude`, which is
 * never committed. A folder that isn't a git checkout is left alone.
 */
export function keepOutOfGit(dir: string, rel: string): void {
  try {
    execFileSync('git', ['check-ignore', '-q', '--', rel], { cwd: dir, stdio: 'ignore' });
    return; // exit 0: already ignored
  } catch (e) {
    if ((e as { status?: number }).status !== 1) return; // 128: not a git checkout
  }
  try {
    let exclude = execFileSync('git', ['rev-parse', '--git-path', 'info/exclude'], { cwd: dir, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
    if (!isAbsolute(exclude)) exclude = join(dir, exclude);
    const line = `/${rel.split('\\').join('/')}`;
    const text = existsSync(exclude) ? readFileSync(exclude, 'utf8') : '';
    if (text.split('\n').some((l) => l.trim() === line)) return;
    mkdirSync(dirname(exclude), { recursive: true });
    appendFileSync(exclude, `${text && !text.endsWith('\n') ? '\n' : ''}${line}\n`);
  } catch { /* best-effort: git status shows the file, and nothing else breaks */ }
}
