import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';

const source = (path, line, contains) => ({ path, line, contains });
const manifest = [
  {
    project: 'julius', pr: 42, sha: 'a6b2cdab895385c5cbcffbd02bb6ed3e66bac05b',
    name: 'compact-output-size', budget: 300,
    query: 'What size comparison must compactOutput pass before it returns changed output?',
    facts: [source('src/economy/compact-output.ts', 39, 'Buffer.byteLength(compact) < Buffer.byteLength(text)')],
  },
  {
    project: 'julius', pr: 44, sha: '64f5b33ae4dd04d303fa773b8abef17fc06c2552',
    name: 'native-backend-decision', budget: 500,
    query: 'What did the opt-in Rust extraction decision say about the TypeScript default, and how does rustExtractorCacheKey identify the backend when JULIUS_EXTRACTOR is unset?',
    facts: [source('.julius/learnings/2026-11-03-opt-in-rust-extraction-keeps-typescript-codex.md', 16, 'keep TypeScript default'),
      source('src/graph/rust.ts', 30, 'process.env.JULIUS_EXTRACTOR !== "rust"'),
      source('src/graph/rust.ts', 50, 'backend === null ? "typescript" : backend.identity')],
  },
  {
    project: 'julius', pr: 40, sha: '810dd5e69570d7b753561a17f266eabff72c695a',
    name: 'stale-context-code', budget: 500,
    query: 'How does inlineSource handle stale crux snippets, and what graph file identity fields does sameFile compare so cache invalidation also catches changes that preserve mtime and size?',
    facts: [source('src/ask/ask.ts', 1283, 'n.summary_state !== "stale" && n.crux?.code'),
      source('src/graph/load.ts', 59, 'a.ctimeMs === b.ctimeMs && a.ino === b.ino && a.dev === b.dev')],
  },
  {
    project: 'julius', pr: 28, sha: '2b4e58a0ba748cba75ceb13c5c1e4f3170b27f54',
    name: 'exact-recovery-guidance', budget: 256,
    query: 'In src/mcp/compact.ts, quote the exact COMPACT_INSTRUCTIONS declaration and the entire context.read dispatch line from the complete-recovery change.',
    facts: [source('src/mcp/compact.ts', 30, 'export const COMPACT_INSTRUCTIONS'),
      source('src/mcp/compact.ts', 85, "if (operation.name === 'context.read')")],
  },
  {
    project: 'bulma', pr: 91, sha: 'f9fc009fe22face91bb74a714e022150a14a842d',
    name: 'answer-fallback-text', budget: 300,
    query: 'What exact fallback message does Bulma Answer safe_reply return when output is sensitive?',
    facts: [source('skills/bulma/scripts/answer_privacy.py', 7, 'SAFE_REPLY ='),
      source('skills/bulma/scripts/answer_privacy.py', 51, 'else SAFE_REPLY')],
  },
  {
    project: 'bulma', pr: 75, sha: '9df26c4bddfa846b26ca107b150c14c7f2d4a3c6',
    name: 'offline-replay-acceptance', budget: 500,
    query: 'What did the process-feedback decision say about dirty replay tree identity, and how does the offline replay check worker success and decide whether the result is accepted?',
    facts: [source('.julius/learnings/2026-11-03-process-feedback-extends-existing-runtime-and-codex.md', 15, 'preserves dirty replay tree identity separately'),
      source('skills/bulma-bus/scripts/replay.py', 140, "worker['exit_code'] == 0 and policy_intact"),
      source('skills/bulma-bus/scripts/replay.py', 144, "status = 'accepted' if verifier['exit_code'] == 0")],
  },
];

export const historicalPlan = {
  shortQueryWordLimit: 15,
  recoveryBudget: 700,
  minimumTrafficReduction: 0.10,
  minimumNewlyComplete: 2,
};

export function historicalCases(juliusRepo, bulmaRepo) {
  const repositories = { julius: resolve(juliusRepo), bulma: resolve(bulmaRepo) };
  return manifest.map(fixture => {
    const repo = repositories[fixture.project];
    const facts = fixture.facts.map(({ path, line, contains }) => {
      const blob = execFileSync('git', ['-C', repo, 'show', `${fixture.sha}:${path}`], { encoding: 'utf8' });
      const text = blob.split('\n')[line - 1];
      assert.ok(text?.includes(contains), `Invalid oracle ${fixture.project}#${fixture.pr} ${path}:${line}`);
      return { path, line, text };
    });
    return { ...fixture, repo, facts, historical: true };
  });
}
