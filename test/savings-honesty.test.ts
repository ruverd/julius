import { test } from 'node:test';
import assert from 'node:assert/strict';
import { savingsTurnNudge, savingsLine, setInputRate, sumSavingsFooters } from '../src/context/savings.js';

test('graph estimates never instruct advertising and cannot enter measured payload accounting', () => {
  setInputRate(3);
  assert.equal(savingsTurnNudge(1000), '');
  const line = savingsLine('x'.repeat(200), { files: 2, baselineChars: 100 });
  assert.match(line, /counterfactual/); assert.match(line, /chars\/4/); assert.match(line, /-25/);
  assert.doesNotMatch(line, /\$|tell the user|tokens saved/);
  assert.equal(sumSavingsFooters(line), 0);
});

test('find-code formatter uses the same honest counterfactual label', async () => {
  const { formatAsk } = await import('../src/ask/ask.js');
  const output = formatAsk({ query: 'sum', mode: 'lexical', hits: [{ kind: 'symbol', title: 'sum', pointer: 'sum.ts:L1-L2', snippet: 's', score: 1, code: 'return a + b;' }], saved: { files: 1, baselineChars: 10000 } } as any);
  assert.doesNotMatch(output, /tokens saved|tell the user/);
  assert.match(output, /counterfactual/);
});

test('inherited agent instructions do not demand hypothetical savings announcements', async () => {
  const { skillTemplate } = await import('../src/claude/skill-template.js');
  const { formatOrientation } = await import('../src/claude/format.js');
  assert.doesNotMatch(skillTemplate(), /Report what julius saved, every turn|tally summing those numbers/);
  assert.doesNotMatch(formatOrientation(''), /one-line tally of the total saved/);
});
