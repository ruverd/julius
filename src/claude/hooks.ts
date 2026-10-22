import { readFileSync, existsSync } from 'node:fs';
import { execFileSync, spawn } from 'node:child_process';
import { join, basename, isAbsolute, relative, resolve } from 'node:path';
import { homedir } from 'node:os';
import { readWiring } from './stats.js';
import { formatBlastRadius, relevantRetrieval, formatOrientation, notesForPrompt, notesOnTouch, standingDirective, type Touch } from './format.js';
import { commitLines, listNotes, setupCommitLine, standingLearnings } from '../notes/notes.js';
import { liveLearnings } from '../notes/learning-fields.js';
import { noteAsk, noteSignals, NOTE_ASKS_PER_SESSION } from './note-signals.js';
import { noteAuthor, teammatesOn } from '../notes/git-facts.js';
import { indexFreshness, staleBanner } from '../context/check.js';
import { patchStats, readStats, acquireLock, readSession, writeSession, resolveContextDir } from './state.js';
import { juliusCliPath, claudeScriptPath } from './paths.js';
import { runUpkeep } from '../upkeep-run.js';
import { runningVersion, wiredHostIds } from '../upkeep.js';
import { hostsWiredForJulius } from '../hosts/registry.js';
import { flushClosedSessions, summarizeSession } from '../telemetry/sessions.js';
import { maybeFlushInBackground } from '../telemetry/flush.js';
import { hasSavingsTally, lastAssistantTurn, lastTurnBilling } from './tally.js';
import { scopeOf, scopesOfGraph } from '../graph/scopes.js';
import { classifyToolUse, commandInvokesJulius, isMcpToolName, isJuliusMcpTool, parseSavings, recordToolUse, type ToolKind } from './session-metrics.js';
import { adoptRepoBrand, brand, cmd, commandOnPath, repoWiredForJulius, tag, juliusOnPath } from '../brand.js';
import { globalCopyCovers } from './hook-layers.js';
import { NOTE_CALL } from '../notes/session-cost.js';
import { keepsNotes, noteCount, repoPlace } from '../notes/home.js';
import { branchesStale, overlapMark, readBranchCache, refreshBranches, SESSION_REFRESH_MS } from '../notes/branches.js';
import { learningFiles } from '../notes/repo-julius.js';
import { inWorkspace, maybeSyncInBackground } from '../cloud/workspace-sync.js';
import { cacheDir, readJson, writeJsonAtomic } from '../util/state.js';
import { countBucket } from '../telemetry/contract.js';
import { track } from '../telemetry/track.js';
import { skillsDirective } from '../skills/skills.js';

/** Prompts shorter than this never trigger retrieval — they are almost always
 * conversational ("yes go ahead", "thanks") and the coverage gate can't judge
 * them reliably with so few terms. */
const MIN_PROMPT_CHARS = 12;

function readStdin(): any {
  const seam = process.env.JULIUS_TEST_STDIN;
  const raw = seam !== undefined ? seam : safeReadFd0();
  try { return JSON.parse(raw); } catch { return {}; }
}
function safeReadFd0(): string { try { return readFileSync(0, 'utf8'); } catch { return ''; } }

function projectDir(input: any): string {
  return process.env.CLAUDE_PROJECT_DIR || input.cwd || process.cwd();
}
export function underJulius(dir: string, file: string): boolean {
  const rel = file.startsWith(dir) ? file.slice(dir.length) : file;
  const posix = rel.replace(/^[/\\]+/, '').replace(/\\/g, '/');
  return posix.startsWith('julius/') || posix.startsWith('.julius/cache/');
}
/** Default budget for a julius child process invoked from a hook, matching the 8s
 * the installed hook entries carry. */
const CHILD_TIMEOUT_MS = 8000;
/** Headroom left for the hook's own work (read stdin, score, write session, emit)
 * after its `julius ask` child returns. */
const HOOK_OVERHEAD_MS = 2000;
/** Floor, so a hand-edited tiny timeout can't leave the child no time at all. */
const MIN_CHILD_TIMEOUT_MS = 4000;

/**
 * How long the prompt hook may let `julius ask` run — derived from the budget that is
 * *actually installed* in this repo's `.claude/settings.json`, not from what the
 * current version of `settings-merge.ts` would install.
 *
 * A query now brings the graph up to date first, so `julius init` raises the
 * UserPromptSubmit budget to 15s to cover the one cold rebuild after an upgrade. But
 * `mergeJuliusSettings` only runs during `julius init` — upgrading the npm package does
 * not re-run it. So every repo wired before that change keeps `"timeout": 8000`, and
 * hard-coding a 13s child there means Claude Code kills the hook first: `emit()` and
 * `writeSession()` never run, the turn gets no retrieval pack at all, and the SIGKILLed
 * child can't even release the build lock. Reading the installed number keeps the child
 * strictly inside whatever budget this repo really has.
 */
export function promptAskTimeout(dir: string): number {
  const installed = installedHookTimeout(dir, 'UserPromptSubmit');
  if (installed === null) return CHILD_TIMEOUT_MS - HOOK_OVERHEAD_MS;
  return Math.max(MIN_CHILD_TIMEOUT_MS, installed - HOOK_OVERHEAD_MS);
}

/**
 * Every settings file Claude Code merges hook definitions from, for a session
 * rooted at `dir`. The per-repo file is not the only place julius's hooks can be
 * installed: declaring them once at the user level wires every repo on the
 * machine at once, and such a repo has no `.claude/settings.json` at all.
 */
function hookSettingsFiles(dir: string): string[] {
  const user = process.env.CLAUDE_CONFIG_DIR ?? join(homedir(), '.claude');
  return [
    join(dir, '.claude', 'settings.json'),
    join(dir, '.claude', 'settings.local.json'),
    join(user, 'settings.json'),
  ];
}

/** The timeout on one settings file's julius hook entry for `event`, or null if it
 * can't be read (no settings file, hand-edited shape, unparseable JSON). */
function hookTimeoutIn(file: string, event: string): number | null {
  try {
    const settings = JSON.parse(readFileSync(file, 'utf8')) as any;
    const blocks = settings?.hooks?.[event];
    if (!Array.isArray(blocks)) return null;
    for (const block of blocks) {
      for (const h of block?.hooks ?? []) {
        if (typeof h?.command === 'string' && /(julius)-hooks\.cjs/.test(h.command) && typeof h.timeout === 'number') {
          return h.timeout;
        }
      }
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * The budget this hook is actually running under, or null when no settings file
 * declares one.
 *
 * The smallest declared timeout wins rather than the nearest, because when more
 * than one file declares the hook Claude Code runs every matching entry and this
 * process cannot tell which one launched it. Guessing high is the expensive
 * mistake: an overrunning child gets the whole hook SIGKILLed, so `emit()` and
 * `writeSession()` never run and the turn silently gets no retrieval at all.
 * Guessing low only shortens one query.
 */
function installedHookTimeout(dir: string, event: string): number | null {
  let smallest: number | null = null;
  for (const file of hookSettingsFiles(dir)) {
    const timeout = hookTimeoutIn(file, event);
    if (timeout === null) continue;
    if (smallest === null || timeout < smallest) smallest = timeout;
  }
  return smallest;
}

/**
 * Append `--dir <contextDir>` for the hooks' own `julius ask`/`julius check`
 * children — the one place in this file that spawns the CLI itself rather
 * than reading `julius/` off disk (which already resolves through
 * `resolveContextDir` inside `util/state.ts` and `claude/stats.ts`). A no-op
 * when `JULIUS_DIR` isn't set, so an unconfigured repo's spawned CLI sees
 * byte-identical argv to before this existed.
 */
function withContextDirArg(dir: string, args: string[]): string[] {
  return process.env.JULIUS_DIR ? [...args, '--dir', resolveContextDir(dir)] : args;
}

function juliusJson(dir: string, args: string[], timeout: number = CHILD_TIMEOUT_MS): any | null {
  try {
    // JULIUS_TEST_CLI is a test seam (mirrors JULIUS_TEST_STDIN/JULIUS_TEST_SYNC_RUN) so
    // tests can point the prompt hook's `julius ask`/`julius check` calls at a stub
    // script and observe the exact args it was invoked with, instead of shelling
    // out to the real CLI (which isn't built relative to the TS source under test).
    const cliPath = process.env.JULIUS_TEST_CLI ?? juliusCliPath();
    const out = execFileSync(process.execPath, [cliPath, ...args],
      { cwd: dir, encoding: 'utf8', timeout, stdio: ['ignore', 'pipe', 'ignore'] });
    return JSON.parse(out);
  } catch (e: any) {
    // `julius check` exits non-zero when the graph is stale (by design) but still
    // prints valid JSON to stdout; recover it from the thrown error before giving up.
    if (e && typeof e.stdout === 'string' && e.stdout.trim()) {
      try { return JSON.parse(e.stdout); } catch { /* not JSON — fall through */ }
    }
    return null;
  }
}
function checkStaleCount(dir: string): number {
  const r = juliusJson(dir, withContextDirArg(dir, ['check', '.', '--json']));
  const g = r?.graph ?? {};
  return (g.changed?.length ?? 0) + (g.added?.length ?? 0) + (g.removed?.length ?? 0);
}
function emit(eventName: string, additionalContext: string): void {
  process.stdout.write(JSON.stringify({ hookSpecificOutput: { hookEventName: eventName, additionalContext } }));
}

/**
 * The absolute path of the file a PostToolUse edit touched, across host edit-tool
 * shapes:
 *   - Claude Code (`Write`/`Edit`/`MultiEdit`) states it directly as
 *     `tool_input.file_path` (already absolute).
 *   - Codex (`apply_patch`) carries the whole patch in `tool_input.command` and
 *     names the file in the patch header (`*** Add File:` / `*** Update File:`),
 *     as a repo-relative path — resolved against `dir` here. Take the first
 *     Add/Update target; that one file is enough to mark the graph dirty and
 *     draw a blast radius (the sync re-checks the whole tree anyway).
 * Returns null when neither shape yields a path, so the hook stays a clean no-op.
 */
export function editedFilePath(input: any, dir: string): string | null {
  const direct = input?.tool_input?.file_path;
  if (typeof direct === 'string' && direct.trim()) return direct;
  const cmd = input?.tool_input?.command;
  if (typeof cmd === 'string' && cmd) {
    const m = /^\*\*\*\s+(?:Add|Update)\s+File:\s+(.+?)\s*$/m.exec(cmd);
    if (m) return isAbsolute(m[1]) ? m[1] : join(dir, m[1]);
  }
  return null;
}

async function handlePostEdit(input: any, dir: string): Promise<void> {
  const file = editedFilePath(input, dir);
  if (!file || underJulius(dir, file)) return;
  patchStats(dir, { dirty: true, staleCount: checkStaleCount(dir), lastFile: basename(file) });
  const out: string[] = [];
  const w = readWiring(dir);
  if (w) { const br = formatBlastRadius(w, file); if (br) out.push(br); }
  const overlap = await editOverlap(input, dir, file);
  if (overlap) out.push(overlap);
  const learned = learningsOnTouch(input, dir);
  if (learned) out.push(learned);
  // One hook, one answer: two JSON objects on stdout would be read as neither.
  if (out.length) emit('PostToolUse', out.join('\n\n'));
}

/** Branch-and-function pairs remembered per session, so each is said once. */
const INJECTED_OVERLAPS_CAP = 40;

/**
 * Under julius, a teammate's open branch that changes the function this edit
 * just changed, for the agent to read and tell the person about, each branch
 * and function once a session. Parsing loads grammars, so it's imported only
 * when the edited file is one some branch changes. Never throws.
 */
async function editOverlap(input: any, dir: string, file: string): Promise<string | null> {
  if (!keepsNotes(dir)) return null;
  try {
    const top = repoPlace(dir);
    if (!top.git) return null;
    const { functionOverlaps, editOverlapDirective } = await import('../notes/edit-overlap.js');
    const found = await functionOverlaps(top.checkout, resolve(dir, file), input?.tool_input, noteAuthor(top.checkout));
    if (!found.length) return null;
    const id = input?.session_id || 'default';
    const s = readSession(dir, id);
    const seen = new Set(s.injectedOverlaps ?? []);
    const fresh = found.filter((o) => o.symbols.some((x) => !seen.has(`${o.ref} ${x.id}`)));
    if (!fresh.length) return null;
    s.injectedOverlaps = [...seen, ...fresh.flatMap((o) => o.symbols.map((x) => `${o.ref} ${x.id}`))].slice(-INJECTED_OVERLAPS_CAP);
    writeSession(dir, id, s);
    const base = readBranchCache(top.checkout)?.base ?? 'origin/main';
    return fresh.slice(0, 2).map((o) => editOverlapDirective(o, base, tag(), overlapMark())).join('\n\n');
  } catch {
    return null;
  }
}

/**
 * The "you're working in backend/, weight it" hint: on a multi-scope repo,
 * narrow the prompt hook's `ask` call to whatever scope the last-edited file
 * (`stats.lastFile`, captured at {@link handlePostEdit}) sits in.
 *
 * `lastFile` is only a basename (not a repo-relative path — see
 * `handlePostEdit`), so this is a best-effort lookup against the CURRENT
 * graph: any file node whose path ends in `/<lastFile>` (or equals it, for a
 * repo-root file). Fails soft in every direction a hook must never crash on —
 * no graph, a single-scope graph, a lastFile no longer in the graph (moved,
 * deleted, or edited before the first build), or a basename that lands in
 * more than one scope (ambiguous: could be either sub-project) all skip the
 * hint silently, logging one line to stderr so the miss is visible without
 * ever failing the hook.
 */
export function lastFileScopeHint(dir: string, lastFile: string | null | undefined): string | null {
  if (!lastFile) return null;
  try {
    const w = readWiring(dir);
    if (!w) return null;
    const scopes = scopesOfGraph(w);
    if (scopes.length <= 1) return null; // single-scope: no hint, no --in
    const matches = (w.nodes ?? []).filter(
      (n) => n.kind === 'file' && (n.path === lastFile || n.path.endsWith(`/${lastFile}`)),
    );
    if (matches.length === 0) {
      console.error(`${tag()} prompt hook: lastFile "${lastFile}" not found in the graph — skipping scope hint`);
      return null;
    }
    const prefixes = new Set(matches.map((n) => scopeOf(n.path, scopes).prefix));
    if (prefixes.size > 1) {
      console.error(`${tag()} prompt hook: lastFile "${lastFile}" matches more than one scope — skipping scope hint`);
      return null;
    }
    const [prefix] = prefixes;
    return prefix === '' ? null : prefix; // root scope: nothing to narrow
  } catch (e: any) {
    console.error(`${tag()} prompt hook: scope hint lookup failed (${e?.message ?? e}) — skipping`);
    return null;
  }
}

/**
 * PostToolUse on a retrieval tool. Two jobs, both a pure parse of the payload the
 * hook already received (no re-run):
 *
 *   1. Score the usage mix: classify the tool as a julius retrieval or a source
 *      read (Read/Grep/Glob) and bump the session's `juliusReads`/`sourceReads`.
 *      Until this ran, those counters were never incremented, so
 *      `session_summary` telemetry shipped 0/0 for every session.
 *   2. Sum any `[julius] tokens saved ≈ N` footers in the output into the running
 *      `savedTokens` total, so the statusline's `~N tok saved` reflects the
 *      session across CLI and MCP.
 *
 * A `[julius]` footer is itself proof julius ran, so it also counts as a julius
 * read even when the tool name alone (a bare `Bash`) couldn't say so. A julius use
 * also flags the turn (`turnUsedJulius`) so the Stop hook's tally can resolve
 * whether the reply told the user what it saved. Stays a no-op on the
 * Write/Edit/unrelated-Bash majority: nothing to classify and no footer means
 * nothing is written.
 */
function handleToolUse(input: any, dir: string): void {
  recordToolUse(dir, input?.session_id || 'default',
    { ...classifyAndScore(input?.tool_name, input?.tool_input?.command, () => input?.tool_response ?? input), host: 'claude-code' });
  const learned = learningsOnTouch(input, dir);
  if (learned) emit('PostToolUse', learned);
}

/**
 * Under julius, the learnings about the file a Read, Edit or Write just touched,
 * or that a shell command (`sed -n 1,40p src/a.ts`, `cat`, a test run) names,
 * each once a session. A julius command is skipped: its own output already
 * carries the learnings that bear on it. Never throws.
 */
export function learningsOnTouch(input: any, dir: string): string | null {
  try {
    if (!keepsNotes(dir)) return null;
    const ti = input?.tool_input ?? {};
    const path = typeof ti.file_path === 'string' ? ti.file_path : typeof ti.notebook_path === 'string' ? ti.notebook_path : null;
    let touch: Touch;
    if (path) {
      const rel = relative(dir, isAbsolute(path) ? path : join(dir, path)).replace(/\\/g, '/');
      if (!rel || rel.startsWith('..') || underJulius(dir, path)) return null;
      touch = { file: rel, verb: input?.tool_name === 'Read' ? 'opened' : 'changed' };
    } else if (typeof ti.command === 'string' && ti.command && !commandInvokesJulius(ti.command)) {
      touch = { command: ti.command };
    } else return null;
    const notes = liveLearnings(listNotes(dir, { branches: false }));
    if (!notes.length) return null;
    const id = input?.session_id || 'default';
    const s = readSession(dir, id);
    const text = notesOnTouch(notes, touch, s);
    if (text) writeSession(dir, id, s);
    return text;
  } catch {
    // A learning that doesn't arrive costs one reminder; a broken hook costs the turn.
    return null;
  }
}

/**
 * Classify a tool use and, only when it could carry a julius footer, parse the
 * savings out of its (lazily-serialised) output.
 *
 * Source reads (Read/Grep/Glob) never print a `[julius]` footer, and their output
 * is a whole file or every match — serialising and regexing that on every read
 * is the expensive, pointless case the widened PostToolUse matcher would
 * otherwise hit. So skip `payload()` entirely for them. For anything else, a
 * footer is itself proof julius ran (a bare `Bash julius …` the name couldn't
 * classify), so its presence upgrades the kind to 'julius'.
 */
function classifyAndScore(
  toolName: string | undefined,
  command: string | undefined,
  payload: () => unknown,
): { kind: ToolKind | null; savedTokens: number } {
  let kind = classifyToolUse(toolName, command);
  if (kind === 'source') return { kind, savedTokens: 0 };
  const savedTokens = parseSavings(JSON.stringify(payload() ?? ''));
  if (savedTokens > 0) kind = 'julius';
  return { kind, savedTokens };
}

/**
 * Cursor `postToolUse` (https://cursor.com/docs/hooks). Same job as
 * {@link handleToolUse} but over Cursor's payload shape: `tool_output` holds the
 * JSON-stringified result (a Shell `julius …` call's footer lives in its stdout),
 * and the session key is `conversation_id`. MCP julius calls are skipped here —
 * `afterMCPExecution` owns them, and counting both would double the julius tally.
 * The skip covers both the prefixed (`MCP:julius_find_code`) and bare
 * (`julius_find_code`) tool-name shapes, so the guard — not just the installed
 * matcher — is what prevents the double count.
 */
function handleCursorPostTool(input: any, dir: string): void {
  const toolName = String(input?.tool_name ?? '');
  if (isMcpToolName(toolName) || isJuliusMcpTool(toolName)) return; // handled by handleCursorMcp
  const command = input?.tool_input?.command ?? input?.tool_input?.cmd;
  recordToolUse(dir, cursorSessionId(input),
    { ...classifyAndScore(toolName, command, () => input?.tool_output ?? input?.tool_response ?? input), host: 'cursor' });
}

/**
 * Cursor `afterMCPExecution`: fires only for MCP tools, so a julius tool is
 * recognised by its name and its savings read out of `result_json`. This is the
 * one place julius MCP calls are counted for Cursor.
 */
function handleCursorMcp(input: any, dir: string): void {
  const toolName = String(input?.tool_name ?? '');
  if (!isJuliusMcpTool(toolName)) return;
  const savedTokens = parseSavings(JSON.stringify(input?.result_json ?? input?.result ?? input ?? ''));
  recordToolUse(dir, cursorSessionId(input), { kind: 'julius', savedTokens, host: 'cursor' });
}

/** Cursor keys a chat by `conversation_id` (its `session_id` equivalent). */
function cursorSessionId(input: any): string {
  return input?.conversation_id || input?.session_id || 'default';
}

/**
 * At turn end: what did this turn's input tokens actually cost?
 *
 * Deliberately ungated, unlike {@link countTallyTurn}: the blended rate has to
 * describe the session, and julius turns are not a fair sample of it — they are
 * the long, tool-heavy, cache-warm ones. Sampling only those would report a
 * cheaper token than the session really pays.
 *
 * Accumulates the pair, never the ratio, so the rate re-blends every turn. A
 * turn already billed (a duplicate Stop, or a Stop racing the transcript write)
 * is skipped on its uuid.
 */
function sampleTurnCost(input: any, dir: string): void {
  try {
    const id = input?.session_id || 'default';
    const billing = lastTurnBilling(input?.transcript_path);
    if (!billing) return;
    const s = readSession(dir, id);
    if (billing.uuid === s.lastBillingUuid) return;
    s.inputCostMicros = (s.inputCostMicros ?? 0) + billing.costMicros;
    s.inputTokensBilled = (s.inputTokensBilled ?? 0) + billing.tokens;
    s.lastBillingUuid = billing.uuid;
    writeSession(dir, id, s);
  } catch {
    // A billing estimate is never worth failing the graph sync over.
  }
}

/**
 * At turn end: did the reply the user just read say what julius saved?
 *
 * Runs only on turns the tool-savings hook flagged, so a conversational turn
 * costs nothing. A turn we cannot observe — a host whose Stop hook names no
 * transcript, an unreadable file, or a Stop that fires before the final prose
 * is on disk — is counted in NEITHER total: the ratio these two numbers form
 * has to mean "of the turns we could check", not "of the turns we tried to".
 */
function countTallyTurn(input: any, dir: string): void {
  try {
    const id = input?.session_id || 'default';
    const s = readSession(dir, id);
    if (!s.turnUsedJulius) return;
    const turn = lastAssistantTurn(input?.transcript_path);
    // Same reply as last time we looked: no new prose has landed, so this Stop
    // is a duplicate or a race with the transcript write. Drop the turn rather
    // than judge it on a stale message.
    if (!turn || turn.uuid === s.lastTallyUuid) {
      writeSession(dir, id, { ...s, turnUsedJulius: false });
      return;
    }
    s.juliusTurns = (s.juliusTurns ?? 0) + 1;
    if (hasSavingsTally(turn.text)) s.reportedTurns = (s.reportedTurns ?? 0) + 1;
    s.turnUsedJulius = false;
    s.lastTallyUuid = turn.uuid;
    writeSession(dir, id, s);
  } catch {
    // A turn-end metric is never worth failing the graph sync over.
  }
}

/** Tool calls in one turn before it counts as digging worth a note. */
export const NOTE_WORTHY_CALLS = 3;

/**
 * Reading that julius's answers stood in for, in one turn, before it counts as
 * digging too. julius answers most questions in one or two calls, so on calls
 * alone an exploratory turn never qualified and its findings were never saved.
 */
export const NOTE_WORTHY_TOKENS = 30_000;

/** The reading a query stood in for, from its `[julius] tokens saved ≈ N` line. A
 * reused learning's own line doesn't count: that digging was done before. */
function codeReadIn(content: unknown): number {
  const text = typeof content === 'string' ? content : Array.isArray(content) ? content.map((c: any) => (typeof c?.text === 'string' ? c.text : '')).join('\n') : '';
  let total = 0;
  for (const m of text.matchAll(/\[(?:julius)\] tokens saved ≈ ([\d,]+)/g)) total += Number(m[1]!.replace(/,/g, '')) || 0;
  return total;
}

/** What the agent is told when a turn took real digging and left no note. */
export const NOTE_ASK =
  '[julius] This took real digging and the session has saved no learning. Before you finish, save one for the next session: ' +
  '`julius note --title "<what it was about>"` with the text on stdin, under ## Decided, ## Tried and ruled out and ## Watch out. ' +
  "A summary, never a transcript, and nothing secret. If you've committed this work, commit the learning too. Then finish as julius's output asks, if it asks anything.";

/**
 * Whether the turn that just ended deserves a note: since the person's last
 * message it made at least NOTE_WORTHY_CALLS tool calls, or julius's answers in
 * it stood in for at least NOTE_WORTHY_TOKENS of reading; and nothing in the
 * session has run `julius note` yet. Pure, for tests: `text` is the
 * transcript's JSONL.
 */
export function turnWantsNote(text: string): boolean {
  let calls = 0;
  let codeRead = 0;
  for (const line of text.split('\n')) {
    if (!line.trim()) continue;
    let e: any;
    try {
      e = JSON.parse(line);
    } catch {
      continue;
    }
    const content = e?.message?.content;
    const blocks: any[] = Array.isArray(content) ? content : [];
    // A message the person typed starts a new turn; a tool result does not.
    if (e?.type === 'user' && (typeof content === 'string' || blocks.some((b) => b?.type === 'text'))) {
      calls = 0;
      codeRead = 0;
    }
    for (const b of blocks) {
      if (b?.type === 'tool_result') codeRead += codeReadIn(b.content);
      if (b?.type !== 'tool_use') continue;
      if (typeof b.input?.command === 'string' && NOTE_CALL.test(b.input.command)) return false;
      calls++;
    }
  }
  return calls >= NOTE_WORTHY_CALLS || codeRead >= NOTE_WORTHY_TOKENS;
}

/**
 * Under julius, a turn that took real digging and left no note is asked once
 * per session to leave one, by blocking the stop with the reason. The agent
 * then saves the note, and julius's output carries on from there (the sign-in
 * link, when one is due). Never blocks twice in a row: Claude Code sets
 * `stop_hook_active` on the stop that follows a block.
 */
function askForNote(input: any, dir: string): void {
  try {
    if (input?.stop_hook_active || !input?.transcript_path || !keepsNotes(dir)) return;
    const id = input?.session_id || 'default';
    const s = readSession(dir, id);
    const asked = s.noteSignalKeys ?? [];
    if (asked.length >= NOTE_ASKS_PER_SESSION) return;
    const next = noteSignals(readFileSync(input.transcript_path, 'utf8'), dir).find((signal) => !asked.includes(signal.key));
    if (!next) return;
    writeSession(dir, id, { ...s, noteAsked: true, noteSignalKeys: [...asked, next.key] });
    process.stdout.write(JSON.stringify({ decision: 'block', reason: noteAsk(next) }));
  } catch {
    // A missed reminder costs one note; a broken Stop hook costs the session.
  }
}

function handleStop(input: any, dir: string): void {
  sampleTurnCost(input, dir);
  countTallyTurn(input, dir);
  // sync-run.js ships next to this module inside the package, so it resolves in
  // any repo that installs julius (not just julius's own). Defensive existsSync:
  // if the package is somehow incomplete, skip rather than wedge on syncing:true.
  // JULIUS_TEST_SYNC_RUN is a test seam (mirrors JULIUS_TEST_STDIN) so tests can point
  // this at a stub file inside their own sandbox instead of writing into src/claude/.
  const syncRun = process.env.JULIUS_TEST_SYNC_RUN ?? claudeScriptPath('sync-run.js');
  if (!existsSync(syncRun)) return;
  const stats = readStats(dir);
  if (stats?.dirty && acquireLock(dir)) {
    patchStats(dir, { syncing: true });
    const child = spawn(process.execPath, [syncRun, dir], { detached: true, stdio: 'ignore', windowsHide: true });
    child.unref();
  }
}

const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * Once a day per repo, the `repo_seen` event: whether `.julius/` is committed
 * here, how many learnings it holds, and whether this machine shares the repo
 * with a workspace. Queued only, like every hook's telemetry.
 */
export function trackRepoSeen(dir: string, now = Date.now()): void {
  try {
    const place = repoPlace(dir);
    if (!place.git) return;
    const mark = join(cacheDir(place.checkout), 'julius-repo-seen.json');
    if (now - (readJson<{ at?: number }>(mark)?.at ?? 0) < DAY_MS) return;
    writeJsonAtomic(mark, { at: now }, true);
    const tracked = execFileSync('git', ['ls-files', '--', '.julius'], { cwd: place.checkout, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], timeout: 3000 });
    track(
      'repo_seen',
      { julius_committed: String(tracked.trim().length > 0), learnings_bucket: countBucket(learningFiles(place.checkout).length), workspace: String(inWorkspace(place.checkout)) },
      { repo: place.checkout },
    );
  } catch {
    // A missed sighting undercounts one repo for one day.
  }
}

/**
 * When the learnings committed on this checkout's HEAD went up since the last
 * session here: how many came in and how many there are, as buckets. A repo
 * with committed learnings is where julius starts paying off, so this is the
 * activation count. `first_look` marks the first time this clone is seen, so
 * a clone of a repo that already had them isn't counted as new ones.
 */
export function trackLearningsCommitted(dir: string): void {
  try {
    const place = repoPlace(dir);
    if (!place.git) return;
    const listed = execFileSync('git', ['ls-tree', '-r', '--name-only', 'HEAD', '--', '.julius/learnings'], {
      cwd: place.checkout, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], timeout: 3000,
    });
    const count = listed.split('\n').filter((f) => f.endsWith('.md')).length;
    const mark = join(cacheDir(place.checkout), 'julius-learnings-committed.json');
    const before = readJson<{ count?: number }>(mark)?.count;
    if (before === count) return;
    writeJsonAtomic(mark, { count }, true);
    if (count <= (before ?? 0)) return;
    track(
      'learnings_committed',
      { added_bucket: countBucket(count - (before ?? 0)), total_bucket: countBucket(count), first_look: String(before === undefined) },
      { repo: place.checkout },
    );
  } catch {
    // Not a repo with a HEAD yet, or git is slow: counted next session.
  }
}

/**
 * Team learnings sitting uncommitted in `.julius/learnings/` (from julius init's
 * read of past sessions, or a session that ended before committing) reach no
 * teammate. Once a day per repo, the first reply says so, with the line that
 * makes the case for committing them. Empty when everything is committed.
 */
export function uncommittedDirective(dir: string, now = Date.now()): string {
  try {
    const place = repoPlace(dir);
    if (!place.git) return '';
    const status = execFileSync('git', ['status', '--porcelain', '--untracked-files=all', '--', '.julius/learnings'], {
      cwd: place.checkout, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], timeout: 3000,
    });
    const n = status.split('\n').filter((l) => l.trimEnd().endsWith('.md')).length;
    const setup = setupUncommitted(place.checkout);
    if (!n && !setup) return '';
    const mark = join(cacheDir(place.checkout), 'julius-uncommitted-said.json');
    if (now - (readJson<{ at?: number }>(mark)?.at ?? 0) < DAY_MS) return '';
    writeJsonAtomic(mark, { at: now }, true);
    if (setup) {
      const line = setupCommitLine(teammatesOn(place.checkout));
      return `${tag()} julius's shared setup here (.julius/ and .claude/settings.json) isn't committed yet, so teammates' Claude can't read the learnings. Say so once, at the end of your first reply, with this line, word for word: ${line}\n`;
    }
    const line = commitLines({}, teammatesOn(place.checkout), 'repo').uncommitted;
    const them = n === 1 ? "learning in .julius/learnings/ isn't committed yet, so no teammate's agent has it" : `learnings in .julius/learnings/ aren't committed yet, so no teammate's agent has them`;
    return `${tag()} ${n} team ${them}. Say so once, at the end of your first reply, with this line, word for word: ${line}\n`;
  } catch {
    return '';
  }
}

/**
 * julius's shared setup isn't in the last commit: `.julius/hook.cjs` isn't
 * tracked, or HEAD's `.claude/settings.json` doesn't run it. Only checked
 * where the hook is on disk, so a repo still set up the old way says nothing.
 */
export function setupUncommitted(checkout: string): boolean {
  if (!existsSync(join(checkout, '.julius', 'hook.cjs'))) return false;
  const git = (args: string[]) => execFileSync('git', args, { cwd: checkout, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], timeout: 3000 });
  try {
    git(['ls-files', '--error-unmatch', '--', '.julius/hook.cjs']);
  } catch {
    return true;
  }
  try {
    return !git(['show', 'HEAD:.claude/settings.json']).includes('/.julius/hook.cjs');
  } catch {
    return true;
  }
}

/** The most the session-start hook waits on `git fetch` for teammates' branches. */
export const BRANCH_FETCH_CAP_MS = 3000;

/**
 * At session start, under julius: read what teammates have pushed, so the
 * session's first prompt already knows their learnings and where their work
 * overlaps; send any learnings and uses the workspace hasn't seen; and count
 * the repo once a day. The fetch is the one wait, capped at
 * BRANCH_FETCH_CAP_MS and skipped when the branches were read in the last
 * minute; a fetch that runs out of time still reads the branches already here.
 * The sync only spawns a detached child.
 */
function juliusAtStart(dir: string): void {
  if (!keepsNotes(dir)) return;
  try {
    const top = repoPlace(dir);
    if (top.git && branchesStale(top.checkout, Date.now(), SESSION_REFRESH_MS)) refreshBranches(top.checkout, { fetchTimeoutMs: BRANCH_FETCH_CAP_MS });
  } catch {
    // Without it, the first prompt sees what the last refresh saw.
  }
  maybeSyncInBackground(dir);
  trackRepoSeen(dir);
  trackLearningsCommitted(dir);
}

/** The repo's committed `.mcp.json` still registers julius's server (set up before 0.23). */
function repoNamesJuliusServer(dir: string): boolean {
  try {
    return Boolean(JSON.parse(readFileSync(join(dir, '.mcp.json'), 'utf8'))?.mcpServers?.julius);
  } catch {
    return false;
  }
}

export async function main(event: string): Promise<void> {
  // julius's own headless Claude calls (the first-run read of past sessions) run with this set.
  if (process.env.JULIUS_NO_HOOKS === '1') return;
  // Registered in the repo and in ~/.claude, Claude Code runs both: one answers.
  if (globalCopyCovers(event, process.argv[1])) return;
  const input = readStdin();
  const dir = projectDir(input);
  adoptRepoBrand(dir, process.env, hostsWiredForJulius);

  if (event === 'session-start') {
    // Before anything is emitted: refresh this repo's wiring if it was written by
    // an older julius, and pick up any cached "newer version on npm" answer.
    // background:false — the registry check stays off the network here; the CLI
    // and the MCP server fill that cache, this only reads it.
    const upkeep = runUpkeep(dir, runningVersion(), { background: false }).lines;
    // Roll up any session that ended since we were last here, then send the
    // queue from a detached child: what session end didn't get to (a killed
    // terminal never fires it) goes now. Once a day at most, never waited on.
    flushClosedSessions(dir);
    maybeFlushInBackground();
    juliusAtStart(dir);
    try {
      const idx = readFileSync(join(resolveContextDir(dir), 'INDEX.md'), 'utf8');
      const banner = staleBanner(indexFreshness(dir)) ?? undefined;
      const kept = keepsNotes(dir);
      const skills = kept ? skillsDirective(dir, cmd('julius skills show')) : '';
      const underJulius = kept && true;
      const standing = underJulius ? standingDirective(standingLearnings(dir)) + uncommittedDirective(dir) : '';
      const mapDir = relative(dir, resolveContextDir(dir)).split('\\').join('/') || 'julius';
      const orientation = formatOrientation(idx, undefined, banner, noteCount(dir), kept, skills + standing, mapDir);
      emit('SessionStart', upkeep.length ? `${upkeep.join('\n')}\n\n${orientation}` : orientation);
    } catch {
      // No INDEX.md (never built here). An upgrade nudge is still worth saying.
      if (upkeep.length) emit('SessionStart', upkeep.join('\n'));
    }
    return;
  }

  // Claude closing: send the queue from a detached child, so quitting isn't slowed.
  if (event === 'session-end') { maybeFlushInBackground(); return; }

  if (event === 'post-edit') { await handlePostEdit(input, dir); return; }

  if (event === 'tool-savings') { handleToolUse(input, dir); return; }

  if (event === 'cursor-post-tool') { handleCursorPostTool(input, dir); return; }

  if (event === 'cursor-mcp') { handleCursorMcp(input, dir); return; }

  // Cursor closes a chat: force-close THIS conversation into a bucketed
  // `session_summary` now (its file's mtime is fresh, so the idle sweep would
  // skip it). Attributed to Cursor. The idle sweep stays on Claude's
  // session-start, whose Stop fires per turn and so has no real end signal.
  if (event === 'cursor-session-end') { summarizeSession(dir, cursorSessionId(input), { host: 'cursor' }); return; }

  if (event === 'stop') { handleStop(input, dir); askForNote(input, dir); return; }

  if (event === 'post-edit-sync') { await handlePostEdit(input, dir); handleStop(input, dir); return; }

  if (event === 'prompt') {
    const prompt = String(input?.prompt ?? '').trim();
    if (prompt.length < MIN_PROMPT_CHARS || prompt.startsWith('<task-notification>')) return;
    // Pointers-only, small, gated. No --source: per-prompt injected tokens are
    // fresh full-price input on every turn (unlike the cached SessionStart
    // orientation), so the pack carries locators, never inlined code — the agent
    // pulls spans itself via `julius ask --source` when a pointer looks right.
    // relevantRetrieval then drops the pack entirely when the prompt barely
    // overlaps the top hit or when every hit was already injected this session.
    const askArgs = withContextDirArg(dir, ['ask', prompt, '.', '--json', '-n', '3']);
    // "You're working in backend/, weight it": only fires on a multi-scope
    // repo whose lastFile resolves cleanly to one scope — see lastFileScopeHint.
    const scopeHint = lastFileScopeHint(dir, readStats(dir)?.lastFile);
    if (scopeHint) askArgs.push('--in', scopeHint);
    const ask = juliusJson(dir, askArgs, promptAskTimeout(dir));
    if (!ask) return;
    const id = input.session_id || 'default';
    const s = readSession(dir, id);
    s.lastQuery = prompt;
    const agent = input?.agent?.name;
    if (agent) s.perAgentQuery[agent] = prompt;
    // Learnings first: what an earlier session worked out matters more than where code is.
    const notes = notesForPrompt(ask, s);
    const txt = [notes, relevantRetrieval(ask, s)].filter(Boolean).join('\n\n');
    if (txt) emit('UserPromptSubmit', txt);
    writeSession(dir, id, s);
  }
}
