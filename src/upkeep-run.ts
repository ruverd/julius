/**
 * The wired-up version of `./upkeep.ts` — one call every entry point makes.
 *
 * Split from `upkeep.ts` so that module stays pure and unit-testable (no init
 * writes, no spawning): this file is the only place that knows how to actually
 * re-run the wiring, and it is deliberately thin.
 */
import { spawn } from 'node:child_process';
import { runInit, wiringName } from './claude/init.js';
import { runHostsInit } from './hosts/init.js';
import { juliusCliPath } from './claude/paths.js';
import { BRAND_ENV, repoWiredForJulius, setBrand, juliusOnPath } from './brand.js';
import { ensureRepoHome } from './notes/home.js';
import { ensureRepoJulius } from './notes/repo-julius.js';
import {
  formatUpdateNudge,
  formatWiringRefresh,
  maybeRefreshInBackground,
  readUpdateCache,
  reconcileWiring,
  wiredHostIds,
  type WiringOpts,
} from './upkeep.js';

export interface UpkeepResult {
  /** Lines worth showing the agent/user, already formatted. Usually empty. */
  lines: string[];
}

/**
 * Re-write the wiring for exactly the hosts a previous `init` chose here, with
 * exactly the flags it was given.
 *
 * `build: false` matters: this runs at session start and at MCP boot, and a graph
 * build there would stall the agent's first turn.
 *
 * The out-of-repo writes (`~/.codex/hooks.json`, `~/.codex/config.toml`) ARE
 * included, because nothing else would ever refresh them: no skill, rule file, or
 * MCP instruction tells an agent to run `julius init`, so leaving them out means a
 * Codex user upgrades the binary and keeps the old hook config forever. They're
 * safe to replay — `installCodexHooks` no-ops when `~/.codex` is absent, rewrites
 * only its own entry (matched on `julius-hooks.cjs`), and reports `unchanged` when
 * the bytes match. A user who declined them at init time is honoured via
 * `opts.global`/`opts.hooks`, replayed from the stamp.
 */
function rewriteWiring(repo: string, hosts: string[], opts: WiringOpts, toJulius = false): void {
  // Moving to julius: everything written from here speaks julius, the repo gets
  // its .julius/, and the hosts are rewired under julius's names.
  if (toJulius) setBrand('julius');
  // Under julius, each refresh also brings `.julius/` and its README up to date.
  if (toJulius || wiringName(repo) === 'julius') {
    const { place } = ensureRepoHome(repo);
    if (place.git) ensureRepoJulius(place.checkout);
  }
  // `opts.global` reaches the claude layer for the same reason `opts.statusline` does:
  // its `~/.claude` writes (hosts/claude-global.ts) are out-of-repo, and a user who
  // declined those at init time must keep declining them on every replay.
  if (hosts.includes('claude'))
    runInit(repo, { build: false, cliPath: juliusCliPath(), statusline: opts.statusline, global: opts.global, ...(toJulius ? { brand: 'julius' as const } : {}) });
  // The other agents move with Claude Code: their julius-named files and
  // fenced blocks are replaced by julius's (see hosts/init.ts).
  const others = hosts.filter((h) => h !== 'claude');
  if (others.length)
    runHostsInit(repo, { agents: others, global: opts.global, mcp: opts.mcp, hooks: opts.hooks, ...(toJulius ? { brand: 'julius' as const } : {}) });
}

/**
 * @param repo    the project dir
 * @param current the running julius's version
 * @param opts.background  false in hook contexts: read the update cache, never
 *   spawn a fetch. Hooks run under a hard timeout and must stay off the network.
 */
export function runUpkeep(
  repo: string,
  current: string,
  opts: { background?: boolean; home?: string } = {},
): UpkeepResult {
  const lines: string[] = [];
  try {
    const refreshed = reconcileWiring(repo, current, { rewrite: rewriteWiring });
    const refreshLine = formatWiringRefresh(refreshed);
    if (refreshLine) lines.push(refreshLine);
  } catch { /* fail-soft: wiring refresh is never worth breaking a session for */ }
  try {
    if (opts.background !== false) maybeRefreshInBackground(opts.home);
    const nudge = formatUpdateNudge(current, readUpdateCache(opts.home)?.latest);
    if (nudge) lines.push(nudge);
  } catch { /* same */ }
  return { lines };
}
