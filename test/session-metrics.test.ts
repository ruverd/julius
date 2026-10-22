import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, utimesSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  classifyToolUse,
  commandInvokesJulius,
  isJuliusMcpTool,
  isMcpToolName,
  parseSavings,
  recordToolUse,
  latestSession,
  formatSessionStats,
} from '../src/claude/session-metrics.js';
import { readSession } from '../src/claude/state.js';

function fresh(): string { return mkdtempSync(join(tmpdir(), 'julius-metrics-')); }

// ── the classifier: the load-bearing table ────────────────────────────────

/**
 * Every host names its tools differently; this is the one place those names are
 * mapped to julius / source / neither. The MCP rows cover the three prefixes a
 * julius tool arrives under across hosts (bare, `MCP:`, `mcp__…__`) — the matcher
 * must recognise all three, since it is what decides whether a call is counted.
 */
const CASES: Array<{ name: string; command?: string; want: 'julius' | 'source' | null }> = [
  // julius MCP tools, every host prefix
  { name: 'julius_find_code', want: 'julius' },
  { name: 'MCP:julius_find_code', want: 'julius' },
  { name: 'mcp__julius__julius_find_code', want: 'julius' },
  { name: 'julius_repo_map', want: 'julius' },
  // native source-read tools (Claude + Cursor)
  { name: 'Read', want: 'source' },
  { name: 'Grep', want: 'source' },
  { name: 'Glob', want: 'source' },
  { name: 'Search', want: 'source' },
  // shell running the julius CLI → julius
  { name: 'Bash', command: 'julius ask "how does auth work"', want: 'julius' },
  { name: 'Shell', command: 'julius map', want: 'julius' },
  { name: 'Shell', command: 'npx -y @ruverd/julius callers foo', want: 'julius' },
  { name: 'Bash', command: 'node dist/cli.js grep bar', want: 'julius' },
  // shell running something else → neither
  { name: 'Bash', command: 'ls -la', want: null },
  { name: 'Shell', command: 'git status', want: null },
  // a path that merely contains "julius" is not an invocation
  { name: 'Bash', command: './myjulius/run.sh', want: null },
  // a third-party MCP tool whose NAME merely contains "julius" is NOT a julius read —
  // the name test is anchored on the real vocabulary, not a loose substring
  { name: 'myjulius_search', want: null },
  { name: 'julius-adjacent-tool', want: null },
  { name: 'some__julius__tool', want: null },
  // edits / spawns / unknown → neither
  { name: 'Write', want: null },
  { name: 'Edit', want: null },
  { name: 'Task', want: null },
  { name: '', want: null },
];

for (const c of CASES) {
  test(`classifyToolUse(${c.name || '∅'}${c.command ? ` :: ${c.command}` : ''}) → ${c.want}`, () => {
    assert.equal(classifyToolUse(c.name, c.command), c.want);
  });
}

test('isJuliusMcpTool recognises julius tools across prefixes, and rejects lookalikes', () => {
  // every host prefix, canonical and legacy names
  assert.ok(isJuliusMcpTool('MCP:julius_find_code'));
  assert.ok(isJuliusMcpTool('mcp__julius__julius_find_code'));
  assert.ok(isJuliusMcpTool('julius_trace_calls'));
  assert.ok(isJuliusMcpTool('julius_ask'), 'a legacy alias still counts');
  // anchored on the real name list — a third-party tool that merely CONTAINS
  // "julius" must not be counted as a julius read
  assert.ok(!isJuliusMcpTool('Read'));
  assert.ok(!isJuliusMcpTool('myjulius_search'));
  assert.ok(!isJuliusMcpTool('julius-adjacent-tool'));
  assert.ok(!isJuliusMcpTool('mcp__other__julius_helper'));
});

test('isMcpToolName recognises the server-prefixed shapes', () => {
  assert.ok(isMcpToolName('MCP:julius_find_code'));
  assert.ok(isMcpToolName('mcp__julius__julius_find_code'));
  assert.ok(!isMcpToolName('Read'));
  assert.ok(!isMcpToolName('Shell'));
});

test('commandInvokesJulius is anchored — not fooled by a substring path', () => {
  assert.ok(commandInvokesJulius('julius ask x'));
  assert.ok(commandInvokesJulius('cd repo && julius map'));
  assert.ok(!commandInvokesJulius('cat myjulius.txt'));
  assert.ok(!commandInvokesJulius('echo upjulius'));
});

// ── parseSavings ───────────────────────────────────────────────────────────

test('parseSavings sums every footer, tolerant of commas', () => {
  assert.equal(parseSavings('nothing here'), 0);
  assert.equal(parseSavings('[julius] tokens saved ≈ 2,181 (89%) — …'), 2181);
  assert.equal(
    parseSavings('a\n[julius] tokens saved ≈ 100 — …\nb\n[julius] tokens saved ≈ 1,000 — …'),
    1100,
  );
});

// ── recordToolUse ──────────────────────────────────────────────────────────

test('recordToolUse increments the right counter and accumulates savings', () => {
  const d = fresh();
  recordToolUse(d, 's1', { kind: 'julius', savedTokens: 500 });
  recordToolUse(d, 's1', { kind: 'julius' });
  recordToolUse(d, 's1', { kind: 'source' });
  const s = readSession(d, 's1');
  assert.equal(s.juliusReads, 2);
  assert.equal(s.sourceReads, 1);
  assert.equal(s.savedTokens, 500);
});

test('recordToolUse is a no-op when there is nothing to record (no file written)', () => {
  const d = fresh();
  recordToolUse(d, 's1', { kind: null, savedTokens: 0 });
  recordToolUse(d, 's1', {});
  // readSession returns the empty default without a file; the proof it never
  // wrote is that a fresh empty session equals what we read.
  const s = readSession(d, 's1');
  assert.equal(s.juliusReads, 0);
  assert.equal(s.sourceReads, 0);
  assert.equal(s.savedTokens, 0);
});

test('recordToolUse can log savings on a julius read with no explicit kind classification', () => {
  const d = fresh();
  recordToolUse(d, 's1', { kind: 'julius', savedTokens: 1990 });
  assert.equal(readSession(d, 's1').savedTokens, 1990);
  assert.equal(readSession(d, 's1').juliusReads, 1);
});

test('recordToolUse stamps the host once — the first tool use owns the attribution', () => {
  const d = fresh();
  recordToolUse(d, 's1', { kind: 'julius', host: 'cursor' });
  assert.equal(readSession(d, 's1').host, 'cursor');
  // a later use from a different host must not overwrite the stamp
  recordToolUse(d, 's1', { kind: 'source', host: 'claude-code' });
  assert.equal(readSession(d, 's1').host, 'cursor', 'host is not re-stamped');
});

// ── latestSession + formatSessionStats (what `julius stats` reads) ──────────

function writeSession(d: string, id: string, body: object, ageMs = 0): void {
  const dir = join(d, '.julius', 'cache', '.cache', 'session');
  mkdirSync(dir, { recursive: true });
  const p = join(dir, `${id}.json`);
  writeFileSync(p, JSON.stringify(body));
  if (ageMs) { const w = new Date(Date.now() - ageMs); utimesSync(p, w, w); }
}

test('latestSession returns null when no session exists', () => {
  assert.equal(latestSession(fresh()), null);
});

test('latestSession picks the most recently touched session file', () => {
  const d = fresh();
  writeSession(d, 'old', { juliusReads: 1, sourceReads: 9 }, 60_000);
  writeSession(d, 'new', { juliusReads: 8, sourceReads: 2 }, 0);
  const s = latestSession(d)!;
  assert.equal(s.id, 'new');
  assert.equal(s.juliusReads, 8);
});

test('formatSessionStats renders the mix, savings and last query', () => {
  const out = formatSessionStats({
    id: 'abc', lastQuery: 'where is auth', perAgentQuery: {},
    juliusReads: 8, sourceReads: 2, savedTokens: 12345,
  });
  assert.match(out, /session abc/);
  assert.match(out, /julius reads:\s+8/);
  assert.match(out, /source reads:\s+2/);
  assert.match(out, /80% julius/);
  assert.match(out, /12,345/);
  assert.match(out, /where is auth/);
});

test('formatSessionStats has a friendly empty state', () => {
  assert.match(formatSessionStats(null), /no session recorded yet/);
});

test('formatSessionStats prices the saving once the session has been billed', () => {
  // Billed $0.60 for 1M input tokens = $0.60/Mtok, so 100k saved is worth $0.06 —
  // which formats as <$0.01? No: $0.06. The point is that it is the MEASURED
  // rate, an order of magnitude under this model's $5/Mtok list price.
  const out = formatSessionStats({
    id: 'abc', lastQuery: null, perAgentQuery: {},
    juliusReads: 8, sourceReads: 2, savedTokens: 100_000,
    inputCostMicros: 600_000, inputTokensBilled: 1_000_000,
  });
  assert.match(out, /tokens saved:\s+~100,000/);
  assert.match(out, /value saved:\s+~\$0\.06/);
});

test('formatSessionStats omits the dollar line rather than claiming zero', () => {
  // Cursor: its hooks name no transcript, so nothing has ever been billed. The
  // token count still stands; a "$0.00" next to it would be a false claim.
  const out = formatSessionStats({
    id: 'abc', lastQuery: null, perAgentQuery: {},
    juliusReads: 8, sourceReads: 2, savedTokens: 100_000,
  });
  assert.match(out, /tokens saved:\s+~100,000/);
  assert.doesNotMatch(out, /value saved/);
  assert.doesNotMatch(out, /\$/);
});
