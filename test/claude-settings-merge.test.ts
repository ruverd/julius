import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mergeJuliusSettings } from '../src/claude/settings-merge.js';

const SL = 'node "${CLAUDE_PROJECT_DIR:-.}/.claude/helpers/julius-statusline.cjs"';

test('empty settings gets the full Julius blocks', () => {
  const { merged, warnings } = mergeJuliusSettings({});
  assert.equal(merged.statusLine.command, SL);
  assert.equal(merged.subagentStatusLine.command, SL);
  assert.ok(Array.isArray(merged.hooks.PostToolUse));
  assert.equal(merged.hooks.PostToolUse[0].matcher, 'Write|Edit|MultiEdit');
  for (const e of ['PostToolUse', 'UserPromptSubmit', 'SessionStart', 'Stop']) {
    assert.ok(merged.hooks[e][0].hooks[0].command.includes('julius-hooks.cjs'), `${e} wired`);
  }
  // PostToolUse carries a second julius block: the usage-mix + tokens-saved
  // accumulator over the retrieval tools (Bash `julius …`, the julius_* MCP tools)
  // and the source-read tools (Read/Grep/Glob) it scores against.
  const savings = merged.hooks.PostToolUse[1];
  assert.equal(savings.matcher, 'Bash|mcp__julius__|Read|Grep|Glob');
  assert.ok(savings.hooks[0].command.includes('tool-savings'), 'savings hook wired');
  assert.ok(merged.footerLinksRegexes.includes('julius/[\\w./-]+\\.md'));
  assert.deepEqual(warnings, []);
});

test('foreign statusLine is preserved with a warning; Julius not forced in', () => {
  const { merged, warnings } = mergeJuliusSettings({ statusLine: { type: 'command', command: 'my-bar.sh' } });
  assert.equal(merged.statusLine.command, 'my-bar.sh');
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /statusLine/);
});

test('a prior Julius statusLine (helper path, old command) is updated to the current command', () => {
  const { merged, warnings } = mergeJuliusSettings({
    statusLine: { type: 'command', command: 'node .claude/helpers/julius-statusline.cjs' },
    subagentStatusLine: { type: 'command', command: 'node .claude/helpers/julius-statusline.cjs' },
  });
  assert.equal(merged.statusLine.command, SL);
  assert.equal(merged.subagentStatusLine.command, SL);
  assert.deepEqual(warnings, []);
});

test('statusline: false does not install a statusLine on empty settings', () => {
  const { merged } = mergeJuliusSettings({}, { statusline: false });
  assert.equal(merged.statusLine, undefined);
  assert.equal(merged.subagentStatusLine, undefined);
  assert.ok(Array.isArray(merged.hooks.Stop), 'hooks still wired');
});

test('statusline: false strips a prior Julius statusLine so a user-level one can show', () => {
  const { merged } = mergeJuliusSettings({
    statusLine: { type: 'command', command: SL },
    subagentStatusLine: { type: 'command', command: SL },
  }, { statusline: false });
  assert.equal(merged.statusLine, undefined);
  assert.equal(merged.subagentStatusLine, undefined);
});

test('statusline: false still leaves a foreign statusLine alone', () => {
  const { merged, warnings } = mergeJuliusSettings(
    { statusLine: { type: 'command', command: 'my-bar.sh' } },
    { statusline: false },
  );
  assert.equal(merged.statusLine.command, 'my-bar.sh');
  assert.match(warnings.join('\n'), /statusLine/);
});

test('JULIUS_NO_STATUSLINE=1 skips installing a statusLine', () => {
  const prev = process.env.JULIUS_NO_STATUSLINE;
  process.env.JULIUS_NO_STATUSLINE = '1';
  try {
    const { merged } = mergeJuliusSettings({});
    assert.equal(merged.statusLine, undefined);
    assert.equal(merged.subagentStatusLine, undefined);
  } finally {
    if (prev === undefined) delete process.env.JULIUS_NO_STATUSLINE;
    else process.env.JULIUS_NO_STATUSLINE = prev;
  }
});

test('existing foreign hooks are preserved; Julius appended', () => {
  const existing = { hooks: { PostToolUse: [{ matcher: 'Bash', hooks: [{ type: 'command', command: 'mine.sh' }] }] } };
  const { merged } = mergeJuliusSettings(existing);
  // foreign block + julius's two PostToolUse blocks (post-edit, tool-savings).
  assert.equal(merged.hooks.PostToolUse.length, 3);
  assert.equal(merged.hooks.PostToolUse[0].hooks[0].command, 'mine.sh');
  assert.ok(merged.hooks.PostToolUse[1].hooks[0].command.includes('julius-hooks.cjs'));
  assert.ok(merged.hooks.PostToolUse[2].hooks[0].command.includes('julius-hooks.cjs'));
});

test('re-running is idempotent (no duplicate Julius entries or footer)', () => {
  const once = mergeJuliusSettings({}).merged;
  const twice = mergeJuliusSettings(once).merged;
  assert.equal(twice.hooks.PostToolUse.length, 2); // post-edit + tool-savings, not duplicated
  assert.equal(twice.hooks.Stop.length, 1);
  assert.equal(twice.footerLinksRegexes.filter((r: string) => r === 'julius/[\\w./-]+\\.md').length, 1);
});

test('foreign top-level keys survive', () => {
  const { merged } = mergeJuliusSettings({ model: 'claude-sonnet-5', permissions: { allow: ['Bash(ls)'] } });
  assert.equal(merged.model, 'claude-sonnet-5');
  assert.deepEqual(merged.permissions.allow, ['Bash(ls)', 'Bash(julius:*)', 'Bash(npx julius:*)', 'Bash(julius-dev:*)', 'Bash(node dist/cli.js:*)']);
});

test('fresh init adds the julius CLI allowlist', () => {
  const { merged } = mergeJuliusSettings({});
  assert.deepEqual(merged.permissions.allow, ['Bash(julius:*)', 'Bash(npx julius:*)', 'Bash(julius-dev:*)', 'Bash(node dist/cli.js:*)']);
});

test('re-init does not duplicate allowlist entries', () => {
  const once = mergeJuliusSettings({}).merged;
  const twice = mergeJuliusSettings(once).merged;
  assert.deepEqual(twice.permissions.allow, ['Bash(julius:*)', 'Bash(npx julius:*)', 'Bash(julius-dev:*)', 'Bash(node dist/cli.js:*)']);
});

test('pre-existing unrelated allow entries are preserved and ours appended', () => {
  const existing = { permissions: { allow: ['Bash(ls)', 'Bash(git:*)'] } };
  const { merged } = mergeJuliusSettings(existing);
  assert.deepEqual(merged.permissions.allow, ['Bash(ls)', 'Bash(git:*)', 'Bash(julius:*)', 'Bash(npx julius:*)', 'Bash(julius-dev:*)', 'Bash(node dist/cli.js:*)']);
});

test('a partially-present allowlist gains only what it lacks, in order', () => {
  const existing = { permissions: { allow: ['Bash(julius:*)'] } };
  const { merged } = mergeJuliusSettings(existing);
  assert.deepEqual(merged.permissions.allow, ['Bash(julius:*)', 'Bash(npx julius:*)', 'Bash(julius-dev:*)', 'Bash(node dist/cli.js:*)']);
});

test('pre-existing allow entries are kept and only the missing ones appended', () => {
  const existing = { permissions: { allow: ['Bash(julius:*)', 'Bash(npx julius:*)'] } };
  const { merged } = mergeJuliusSettings(existing);
  assert.deepEqual(merged.permissions.allow, ['Bash(julius:*)', 'Bash(npx julius:*)', 'Bash(julius-dev:*)', 'Bash(node dist/cli.js:*)']);
});

test('permissions object with no allow key gets one added; other keys preserved', () => {
  const existing = { permissions: { deny: ['Bash(rm:*)'] } };
  const { merged } = mergeJuliusSettings(existing);
  assert.deepEqual(merged.permissions.deny, ['Bash(rm:*)']);
  assert.deepEqual(merged.permissions.allow, ['Bash(julius:*)', 'Bash(npx julius:*)', 'Bash(julius-dev:*)', 'Bash(node dist/cli.js:*)']);
});
