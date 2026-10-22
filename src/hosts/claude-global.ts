/**
 * User-level install for Claude Code: the copy of julius's wiring that lives
 * outside every repo.
 *
 * Why this exists. Everything `julius init` writes for Claude Code lands *in* the
 * repo — `.mcp.json` and `.claude/settings.json`. A `.gitignore` is free to ignore
 * both, and `git worktree add` checks out tracked files only, so a worktree of such
 * a repo starts with julius's shims present and neither of the two files that *point
 * at* them. No settings.json means no SessionStart hook; no `.mcp.json` means no
 * tool server. julius is absent, silently, in a tree that looks correctly wired.
 *
 * julius already carries the repair for exactly that — `reconcileWiring` rewrites
 * both files — and it is unreachable here: `runUpkeep` is called only from the hook
 * and from the MCP server, which are the two things that are missing. Seeding can't
 * help either, since it runs on the query path, which needs the server.
 *
 * So the fix cannot live in the repo. `~/.claude/` is not in anyone's working tree,
 * no `.gitignore` reaches it, and Claude Code reads it for every project — worktrees
 * included. Codex has been installed this way from the start (see ./codex-hooks.ts,
 * whose own note says the entries "fire in every repo opened with Codex, not just
 * this one"); Claude Code was the one host julius wired repo-only. This module closes
 * that gap, and is a deliberate mirror of that file.
 *
 * The repo-level writes stay exactly as they were. A project that has its own
 * `.mcp.json` and settings keeps using them; this is the floor underneath, not a
 * replacement.
 */
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { hooksShim } from '../claude/shim-template.js';
import { mergeJuliusHooks } from '../claude/settings-merge.js';
import { toPosixPath } from '../util/paths.js';
import { readJsonObject, writeOwned, type ConfigWrite } from './config-write.js';
import type { PlannedWrite } from './plan.js';
import type { Brand } from '../brand.js';

/** Same `{ id, path, action }` contract every other writer in this layer reports. */
export type GlobalWrite = ConfigWrite;

/** The directory the user-level shim lives in — the base every hook command names. */
export function globalHelpersDir(home: string): string {
  return join(home, '.claude', 'helpers');
}

/**
 * The files a user-level install would touch — pure, no writes, so `--dry-run` and
 * the picker can report them up front. Both are scoped 'global': they apply to
 * every project opened with Claude Code, not just this one.
 */
export function claudeGlobalTargets(home: string, brand: Brand = 'julius'): PlannedWrite[] {
  const g = (id: string, path: string, kind: PlannedWrite['kind'], what: string): PlannedWrite =>
    ({ hostId: 'claude', id, path, scope: 'global', kind, what });
  return [
    g('claude-global-shim', join(globalHelpersDir(home), 'julius-hooks.cjs'), 'hook', 'hooks shim (user level)'),
    g('claude-global-hooks', join(home, '.claude', 'settings.json'), 'hook', 'SessionStart / UserPromptSubmit / PostToolUse / Stop / SessionEnd'),
  ];
}

/** Merge julius's hook blocks into a settings file, preserving everything else. */
function upsertGlobalHooks(id: string, path: string, helpers: string): GlobalWrite {
  const loaded = readJsonObject(path);
  if (loaded === 'unparseable') return { id, path, action: 'skipped-unparseable' };
  const { root: existing, existed } = loaded;
  const before = JSON.stringify(existing);
  const { merged } = mergeJuliusHooks(existing, helpers);
  if (JSON.stringify(merged) === before) return { id, path, action: 'unchanged' };
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(merged, null, 2)}\n`);
  return { id, path, action: existed ? 'updated' : 'created' };
}

/**
 * Install the user-level shim and hook entries, removing stale Julius MCP wiring.
 *
 * The shim is written to `home` and the hook commands name it by absolute path, for
 * the reason the repo form can't be reused: `${CLAUDE_PROJECT_DIR}/.claude/helpers/`
 * resolves inside whatever project is open, and the whole point is to work in one
 * that has no such file. The shim itself is the same one every host gets, and finds
 * the installed package the same way (see claude/shim-template.ts).
 *
 * Best-effort by contract, like every other writer here: a failure is reported as an
 * action, never raised, so a bad `~/.claude.json` can't fail a `julius init`.
 */
export function installClaudeGlobal(home: string, brand: Brand = 'julius'): GlobalWrite[] {
  const [shim, settings] = claudeGlobalTargets(home, brand);
  const mcp = { id: 'claude-global-mcp', path: join(home, '.claude.json') };
  const out: GlobalWrite[] = [];

  try {
    out.push(writeOwned(shim.id, shim.path, hooksShim(), 0o755));
  } catch {
    out.push({ id: shim.id, path: shim.path, action: 'skipped-unparseable' });
  }

  // Only wire the hooks once the shim they call is actually on disk — a hook
  // entry pointing at a missing file is an error in every session, which is a
  // worse failure than not installing.
  if (out[0].action !== 'skipped-unparseable') {
    try {
      // Posix form in the command string: `join` gives backslashes on Windows and
      // the template appends `/julius-hooks.cjs`, so the raw path produces a mixed
      // `C:\Users\…\helpers/julius-hooks.cjs`. Node accepts forward slashes on
      // Windows, so one separator throughout is both correct and readable.
      out.push(upsertGlobalHooks(settings.id, settings.path, toPosixPath(globalHelpersDir(home))));
    } catch {
      out.push({ id: settings.id, path: settings.path, action: 'skipped-unparseable' });
    }
  }

  // Remove a stale Julius server; current Claude Code wiring uses hooks.
  out.push(dropUserServer(mcp.id, mcp.path, 'julius'));

  return out;
}

/** Remove one user-scope server from `~/.claude.json`, leaving everything else. */
function dropUserServer(id: string, path: string, name: string): GlobalWrite {
  try {
    const loaded = readJsonObject(path);
    if (loaded === 'unparseable') return { id, path, action: 'skipped-unparseable' };
    const servers = loaded.root.mcpServers;
    if (!servers || typeof servers !== 'object' || !(name in servers)) return { id, path, action: 'unchanged' };
    delete servers[name];
    writeFileSync(path, `${JSON.stringify(loaded.root, null, 2)}\n`);
    return { id, path, action: 'updated' };
  } catch {
    return { id, path, action: 'skipped-unparseable' };
  }
}

/**
 * In a repo wired for julius, Claude Code would list julius's user-level server
 * beside the repo's own `julius` one: the same tools twice. Claude Code keeps a
 * per-folder switch for that, `projects["<folder>"].disabledMcpServers` in
 * `~/.claude.json` (what /mcp sets), so julius goes off for this folder only
 * and keeps serving every repo still wired as julius. Nothing to do when julius
 * has no user-level server. Best-effort, like every writer here.
 */
export function disableJuliusServerIn(home: string, folder: string): GlobalWrite {
  const id = 'claude-folder-julius-off';
  const path = join(home, '.claude.json');
  try {
    const loaded = readJsonObject(path);
    if (loaded === 'unparseable') return { id, path, action: 'skipped-unparseable' };
    const root = loaded.root;
    if (!root.mcpServers?.julius) return { id, path, action: 'unchanged' };
    const projects = (root.projects ??= {}) as Record<string, { disabledMcpServers?: unknown }>;
    const here = (projects[folder] ??= {});
    const off = Array.isArray(here.disabledMcpServers) ? (here.disabledMcpServers as string[]) : [];
    if (off.includes('julius')) return { id, path, action: 'unchanged' };
    here.disabledMcpServers = [...off, 'julius'];
    writeFileSync(path, `${JSON.stringify(root, null, 2)}\n`);
    return { id, path, action: 'updated' };
  } catch {
    return { id, path, action: 'skipped-unparseable' };
  }
}
