import { test } from 'node:test';
import assert from 'node:assert/strict';
import { skillTemplate } from '../src/claude/skill-template.js';

test('skill template is a well-formed SKILL.md', () => {
  const src = skillTemplate();
  assert.ok(src.startsWith('---\n'), 'starts with YAML frontmatter');
  assert.match(src, /^name: julius$/m, 'declares name: julius');
  assert.match(src, /^description:/m, 'has a description');
  const body = src.split(/\n---\n/)[1] ?? '';
  assert.ok(body.trim().length > 0, 'has a non-empty body');
  assert.match(body, /julius ask/, 'body tells the agent to use `julius ask`');
  assert.match(body, /every occurrence/i, 'body teaches the exhaustive-task grep rule');
  assert.match(body, /julius callers/, 'body teaches the callers command');
  assert.match(body, /--direction out/, 'body teaches callees via --direction out');
  assert.match(body, /--depth/, 'body teaches blast radius via --depth');
  assert.match(body, /truncated/i, 'body tells the agent to follow up on truncated spans');
  assert.match(body, /julius grep/, 'body routes sweeps to julius grep');
  assert.match(body, /julius map/, 'body tells the agent to orient with julius map before exploring');
  assert.match(body, /\[scope\/\]/, 'body teaches the [scope/] label on multi-scope hits');
  assert.match(body, /--in <scope>\//, 'body teaches narrowing with ask --in <scope>/');
  assert.match(body, /counterfactual/i, 'body labels graph accounting honestly');
  assert.doesNotMatch(body, /tally summing those numbers/i, 'no promotional tally instruction');
});
