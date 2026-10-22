/**
 * Session usage accounting, shared across every host (Claude Code, Cursor, and
 * plain MCP). It answers the one question the README rests on: when an agent had
 * both julius and grep in front of it, which did it reach for, and how much did
 * that save?
 *
 * The counters (`juliusReads`, `sourceReads`, `savedTokens`) already live on
 * {@link SessionState}; before this module nothing ever incremented the first
 * two, so `session_summary` telemetry shipped 0/0 for every session. Everything
 * here is a pure classify + read-modify-write over `julius/.cache/session/`, so a
 * host adapter is a few lines: parse its payload, call {@link recordToolUse}.
 *
 * Two payload shapes feed it, confirmed against the vendor docs rather than
 * guessed (the matcher depends on getting the names right):
 *
 *   - Claude Code `PostToolUse`  — `{ tool_name, tool_input: { command }, tool_response }`.
 *     A julius retrieval prints a `[julius] tokens saved ≈ N` footer into
 *     `tool_response`, which is itself proof julius ran.
 *   - Cursor `postToolUse`       — `{ tool_name, tool_input, tool_output, conversation_id }`
 *     (https://cursor.com/docs/hooks). `tool_output` is the JSON-stringified
 *     result; a Shell `julius …` call carries the same footer inside its stdout.
 *   - Cursor `afterMCPExecution` — `{ tool_name, tool_input, result_json, duration }`.
 *     Fires only for MCP tools, so a julius tool is recognised by its name and
 *     its savings read out of `result_json`.
 *
 * MCP tool names arrive host-prefixed in different shapes (`julius_find_code`,
 * `MCP:julius_find_code`, `mcp__julius__julius_find_code`). {@link isJuliusMcpTool}
 * strips the prefix to the last delimited segment and checks it against the real
 * name list (`JULIUS_MCP_TOOL_NAMES`), so a julius tool is recognised across every
 * host format while a third-party tool that merely contains "julius" is not.
 */
import { statSync } from 'node:fs';
import { join } from 'node:path';
import { sumSavingsFooters } from '../context/savings.js';
import { dollarsSaved, formatDollars } from '../context/price.js';
import { readSession, writeSession, sessionDir, listSessionIds, type SessionState } from './state.js';
import type { AgentHost } from '../telemetry/contract.js';
import { JULIUS_MCP_TOOL_NAMES } from '../mcp/tool-names.js';
import { brand, cmd } from '../brand.js';

export type ToolKind = 'julius' | 'source';

/** Native tools that mean "the agent went to read source itself" — the grep/read
 *  path julius is meant to replace. These are the host tool NAMES (Claude Code and
 *  Cursor both use Read/Grep/Glob; Cursor adds Search); shell builtins like `ls`
 *  are commands, never tool names, so they belong to the Shell branch, not here.
 *  Compared lower-cased. */
const SOURCE_TOOLS = new Set(['read', 'grep', 'glob', 'search']);

/** The host's shell tool, whose `command` we then inspect for a julius invocation. */
function isShellTool(t: string): boolean {
  return t === 'bash' || t === 'shell';
}

/** An MCP-style tool name (server-prefixed), as opposed to a native Read/Shell.
 *  Used to hand julius MCP calls to the dedicated MCP hook so a host that fires
 *  BOTH a generic post-tool hook and an MCP hook can't double-count them. */
export function isMcpToolName(toolName: string): boolean {
  const t = toolName.toLowerCase();
  return t.startsWith('mcp') || t.includes(':') || t.includes('__');
}

/**
 * Whether a tool name is one of julius's MCP tools, across every host prefix.
 * Anchored on the real name list (`julius_find_code`, its legacy aliases, …), not
 * a loose `includes('julius')`: a third-party MCP tool whose name merely contains
 * "julius" (or a repo working on julius itself) must not count as a julius read —
 * the same care `commandInvokesJulius` takes for the CLI side. Strips the host
 * prefix first (`mcp__julius__julius_find_code`, `MCP:julius_find_code`) by taking
 * the last delimited segment. */
export function isJuliusMcpTool(toolName: string): boolean {
  const t = toolName.toLowerCase();
  const bare = t.split(/[:./]|__/).pop() ?? t;
  return JULIUS_MCP_TOOL_NAMES.has(bare);
}

/** Whether a shell command line invokes the CLI under either name (any of its install shapes). */
export function commandInvokesJulius(command: string): boolean {
  const c = command.trim();
  // running from a source checkout
  if (/dist[/\\](cli|bin[/\\]julius)\.js/.test(c)) return true;
  // `julius …`, `julius-dev …`, `npx [-y] [@ruverd/]julius …`, and the same for
  // `julius` / `@ruverd/julius`, at the start of the line or of a &&/;/| segment —
  // not "myjulius" or a path that merely contains it.
  return /(^|[|&;]\s*)(npx\s+(-y\s+)?(@ruverd\/)?)?julius(-dev)?\b/i.test(c);
}

/**
 * Classify one tool use as a julius retrieval, a source read, or neither
 * (an edit, a task spawn, an unrelated shell command — no retrieval signal).
 * `command` is the shell command line when `toolName` is the host's shell tool.
 */
export function classifyToolUse(toolName?: string, command?: string): ToolKind | null {
  const t = (toolName ?? '').toLowerCase();
  if (!t) return null;
  if (isJuliusMcpTool(t)) return 'julius';
  if (SOURCE_TOOLS.has(t)) return 'source';
  if (isShellTool(t) && command && commandInvokesJulius(command)) return 'julius';
  return null;
}

/** Sum every `[julius] tokens saved ≈ N` footer in a blob of tool output. Thin
 *  alias over {@link sumSavingsFooters}, which lives next to the code that writes
 *  the footer so the two can't drift. */
export function parseSavings(blob: string): number {
  return sumSavingsFooters(blob);
}

export interface ToolUse {
  /** 'julius' → juliusReads++, 'source' → sourceReads++, null/absent → neither. */
  kind?: ToolKind | null;
  /** Tokens the retrieval saved, parsed from its footer. Added to the running total. */
  savedTokens?: number;
  /** The host recording this use. Stamped on the session file (once) so the
   * `session_summary` is attributed correctly no matter which host later flushes it. */
  host?: AgentHost;
}

/**
 * Fold one tool use into a session's counters. A no-op when there is nothing to
 * record (kind null and no savings), so a host can call it unconditionally after
 * every tool without first checking whether the tool was interesting — the
 * no-write path is what keeps it cheap on the Write/Edit/Task majority.
 *
 * Best-effort read-modify-write, not locked — mirroring `patchStats` in
 * util/state.ts. Two tool-use hooks racing on the same session file can lose a
 * count; that is acceptable for an episodic usage estimate (worst case is an
 * undercount by one, never corruption thanks to the atomic write), and a lock
 * here would contend with the build lock these hooks also touch.
 */
export function recordToolUse(dir: string, sessionId: string, use: ToolUse): void {
  const saved = use.savedTokens ?? 0;
  if (!use.kind && saved <= 0) return;
  const id = sessionId || 'default';
  const s = readSession(dir, id);
  if (use.kind === 'julius') s.juliusReads = (s.juliusReads ?? 0) + 1;
  else if (use.kind === 'source') s.sourceReads = (s.sourceReads ?? 0) + 1;
  if (saved > 0) s.savedTokens = (s.savedTokens ?? 0) + saved;
  // A julius use owes a tally in this turn's reply; the Stop hook (countTallyTurn)
  // resolves whether it got one and clears the flag. A flag, not a count — a turn
  // with several julius calls is still one reply to the user.
  if (use.kind === 'julius') s.turnUsedJulius = true;
  // Stamp the host once; the first tool use that lands owns the attribution.
  if (use.host && !s.host) s.host = use.host;
  writeSession(dir, id, s);
}

export interface SessionSummary extends SessionState {
  id: string;
}

/** The most-recently-touched session file for a repo, or null when none exist —
 *  what `julius stats` shows by default: the session you were just in. */
export function latestSession(dir: string): SessionSummary | null {
  const sdir = sessionDir(dir);
  let bestId: string | null = null;
  let bestMtime = -Infinity;
  for (const id of listSessionIds(dir)) {
    let mtime: number;
    try { mtime = statSync(join(sdir, `${id}.json`)).mtimeMs; } catch { continue; }
    if (mtime > bestMtime) { bestMtime = mtime; bestId = id; }
  }
  if (bestId === null) return null;
  return { id: bestId, ...readSession(dir, bestId) };
}

/**
 * A one-line-per-fact readout of a session's usage mix — Cursor has no
 * statusline, so this is how you see the numbers the Claude Code bar would show.
 * Reads local JSON only; sends nothing.
 */
/**
 * What this repo's most recent session has actually been paying per million
 * input tokens, or null when no turn has been billed yet.
 *
 * `latestSession` rather than a session id because the callers are CLI and MCP
 * processes answering one query: they know the repo, never the host's session
 * id. The rate belongs to the repo's current session, which is the one whose
 * reply the number is about to appear in.
 */
export function sessionInputRate(dir: string): number | null {
  const s = latestSession(dir);
  if (!s?.inputCostMicros || !s?.inputTokensBilled) return null;
  // Micro-dollars per token and dollars per million tokens are the same number:
  // both divide by 1e6 once. Returned as $/Mtok because that is the unit the
  // price table is written in and the one a reader can sanity-check against it.
  return s.inputCostMicros / s.inputTokensBilled;
}

export function formatSessionStats(s: SessionSummary | null): string {
  if (s === null) {
    return `${cmd('julius status')}: no session recorded yet — use ${brand()} in an agent session, then look again.`;
  }
  const julius = s.juliusReads ?? 0;
  const source = s.sourceReads ?? 0;
  const saved = s.savedTokens ?? 0;
  const total = julius + source;
  const mix =
    total === 0 ? 'no retrieval yet' : `${Math.round((julius / total) * 100)}% julius`;
  const lines = [
    `${cmd('julius status')} — session ${s.id}`,
    `  julius reads:   ${julius}`,
    `  source reads:  ${source}   (Read / Grep / Glob)`,
    `  mix:           ${mix}`,
    `  tokens saved:  ~${saved.toLocaleString()}`,
  ];
  // Omitted, not zeroed, when no turn has been billed yet: a host whose hooks
  // name no transcript can't know what a token costs here, and a made-up rate
  // would be worse than the silence.
  const usd = dollarsSaved(saved, s.inputCostMicros, s.inputTokensBilled);
  if (usd !== null) lines.push(`  value saved:   ~${formatDollars(usd)}`);
  if (s.lastQuery) lines.push(`  last query:    ${s.lastQuery}`);
  return lines.join('\n');
}
