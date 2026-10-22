/**
 * Under julius, a turn that took real digging and left no note is asked, once
 * a session, to leave one: the Stop hook blocks the stop with the reason.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { BRAND_ENV } from '../src/brand.js';
import { main } from '../src/claude/hooks.js';
import { noteSignals } from '../src/claude/note-signals.js';
import { ensureRepoHome } from '../src/notes/home.js';

const prompt = (text: string) => ({ type: 'user', message: { role: 'user', content: text } });
const call = (command: string) => ({ type: 'assistant', message: { role: 'assistant', content: [{ type: 'tool_use', id: Math.random().toString(36), name: 'Bash', input: { command } }] } });
const result = () => ({ type: 'user', message: { role: 'user', content: [{ type: 'tool_result', tool_use_id: 'x', content: 'ok' }] } });
const jsonl = (entries: object[]) => entries.map((e) => JSON.stringify(e)).join('\n');

const tool = (id: string, command: string) => ({ type: 'assistant', message: { role: 'assistant', content: [{ type: 'tool_use', id, name: 'Bash', input: { command } }] } });
const toolResult = (id: string, error: boolean, text: string) => ({ type: 'user', message: { role: 'user', content: [{ type: 'tool_result', tool_use_id: id, is_error: error, content: text }] } });

test('a busy turn with no real signal does not ask for a note', () => {
  const dig = [prompt('why does Do hang'), call('julius ask "do"'), result(), call('sed -n 1,9p client.go'), result(), call('go test ./...'), result(), call('grep -n x client.go'), result()];
  assert.deepEqual(noteSignals(jsonl(dig), '/repo'), []);
  assert.deepEqual(noteSignals('not json\n', '/repo'), []);
});

test('a shell rewrite that makes a failing check pass is a signal', () => {
  const transcript = [
    prompt('fix the retry limit'),
    tool('t1', 'npm test'),
    toolResult('t1', true, 'FAIL src/retry.test.ts'),
    tool('e1', "sed -i '' 's/retry_limit=3/retry_limit=7/' src/listing.ts"),
    toolResult('e1', false, ''),
    tool('t2', 'npm test'),
    toolResult('t2', false, '# fail 0'),
  ];
  const signals = noteSignals(jsonl(transcript), '/repo');
  assert.equal(signals[0]?.kind, 'fixed');
  assert.match(signals[0]?.what ?? '', /sed -i|npm test/);
});

test('an exploratory turn julius answered in one call still wants a note when the answer stood in for real reading', () => {
  const ask = (footer: string) => [
    prompt('how does checkout pick a carrier'),
    tool('ask1', 'julius ask "carrier" --source'),
    toolResult('ask1', false, `${footer}\n\n1. pickCarrier · function`),
  ];
  assert.equal(noteSignals(jsonl(ask('[julius] tokens saved ≈ 42,739 (98%)')), '/repo')[0]?.kind, 'explored');
  assert.deepEqual(noteSignals(jsonl(ask('[julius] tokens saved ≈ 4,200 (61%)')), '/repo'), []);
  assert.deepEqual(noteSignals(jsonl(ask('[julius] learnings saved ≈ 900,000 tokens')), '/repo'), []);
  assert.deepEqual(
    noteSignals(jsonl([...ask('[julius] tokens saved ≈ 42,739 (98%)'), prompt('thanks'), call('ls'), result()]), '/repo'),
    [],
  );
});

async function stop(input: object): Promise<string> {
  let out = '';
  const write = process.stdout.write.bind(process.stdout);
  process.stdout.write = ((chunk: string | Uint8Array) => ((out += String(chunk)), true)) as typeof process.stdout.write;
  process.env.JULIUS_TEST_STDIN = JSON.stringify(input);
  try {
    await main('stop');
  } finally {
    process.stdout.write = write;
    delete process.env.JULIUS_TEST_STDIN;
  }
  return out;
}

test('the Stop hook asks once a session, and never on the stop after a block', async () => {
  process.env.JULIUS_HOME = mkdtempSync(join(tmpdir(), 'note-ask-home-'));
  process.env[BRAND_ENV] = 'julius';
  const d = mkdtempSync(join(tmpdir(), 'note-ask-repo-'));
  mkdirSync(join(d, '.julius', 'cache', '.cache', 'session'), { recursive: true });
  process.env.CLAUDE_PROJECT_DIR = d;
  ensureRepoHome(d);
  const t = join(d, 't.jsonl');
  writeFileSync(t, jsonl([
    prompt('fix the retry limit'),
    tool('t1', 'npm test'),
    toolResult('t1', true, 'FAIL src/retry.test.ts'),
    tool('e1', "sed -i '' 's/retry_limit=3/retry_limit=7/' src/listing.ts"),
    toolResult('e1', false, ''),
    tool('t2', 'npm test'),
    toolResult('t2', false, '# fail 0'),
  ]));

  assert.equal(await stop({ session_id: 's1', transcript_path: t, stop_hook_active: true }), '', 'not on the stop a block caused');
  const first = await stop({ session_id: 's1', transcript_path: t });
  const asked = JSON.parse(first) as { decision: string; reason: string };
  assert.equal(asked.decision, 'block');
  assert.match(asked.reason, /julius note/);
  assert.equal(await stop({ session_id: 's1', transcript_path: t }), '', 'once a session');
  assert.notEqual(await stop({ session_id: 's2', transcript_path: t }), '', 'a new session is asked again');
});
