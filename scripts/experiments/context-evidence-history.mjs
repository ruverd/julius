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

// These cases were pinned before running the directed-recovery implementation.
const holdout = [
  {
    project: 'julius', pr: 32, sha: 'db02ae2d721a0e5f3fbfa39eaff607f3d2929788',
    name: 'prepared-docs-hit', budget: 300,
    query: 'What does preparedAskDocs return on a cache hit?',
    facts: [source('src/ask/prepared-index.ts', 15, 'if (cached) return cached')],
  },
  {
    project: 'julius', pr: 30, sha: '22d09249ffcf17178c53998fc0849d95c417db93',
    name: 'verified-index-reuse', budget: 450,
    query: 'What did the investigation decision say about verification and index reuse, and how does loadVerifiedGraph check configurationHash and source hashes?',
    facts: [source('.julius/learnings/2026-10-23-reuse-verified-indexes-and-defer-provider-ruver.md', 20, 'Reuse that proof independently of report-cache presence'),
      source('src/investigation/index.ts', 95, 'verification.configurationHash !== snapshot.configurationHash'),
      source('src/investigation/index.ts', 97, 'Object.entries(snapshot.hashes).every')],
  },
  {
    project: 'julius', pr: 33, sha: 'fa969f05e0f4d26a8b1f4bffb5ba39884af9a6c4',
    name: 'exact-tool-and-fallback-guidance', budget: 256,
    query: 'In src/claude/skill-template.ts, give the exact When julius isn\'t enough fallback passage and the complete julius_call tool guidance that follows it.',
    passages: [{ path: 'src/claude/skill-template.ts', from: 288, to: 300 }],
  },
  {
    project: 'bulma', pr: 83, sha: '7303a61b9fa64575b8f8f1cd5cd8844b9992c069',
    name: 'review-reference-validation', budget: 400,
    query: 'In skills/bulma-lstm/scripts/review-actions.py, which guards reject a review ID from plan(state) and plan(live) before dismissal?',
    facts: [source('skills/bulma-lstm/scripts/review-actions.py', 62, "review_id not in plan(state)['dismiss']"),
      source('skills/bulma-lstm/scripts/review-actions.py', 78, "review_id not in plan(live)['dismiss']")],
    wrongReference: 'skills/bulma-lstm/scripts/review-action.py',
  },
  {
    project: 'bulma', pr: 85, sha: '22d0ef8d1501770812b3aef2bef95ebafe857ed5',
    name: 'ambiguous-model-attribution', budget: 300,
    query: 'When does model_identity.identity omit model attribution for ambiguous records?',
    facts: [source('skills/bulma-host/scripts/model_identity.py', 15, "value.get('ambiguous') is True"),
      source('skills/bulma-host/scripts/model_identity.py', 16, 'return {}')],
  },
];

export const historicalPlan = {
  shortQueryWordLimit: 15,
  recoveryBudget: 700,
  minimumTrafficReduction: 0.10,
  minimumNewlyComplete: 2,
};

const marginalHoldout = [
  {
    project: 'julius', pr: 25, sha: '00b1fce23b1434a88ed162aa3469b47b143e7d90',
    name: 'literal-match-limit', budget: 300,
    query: 'How does scanLiterals separate its hit limit from its total count?',
    facts: [source('src/economy/delivery.ts', 135, 'hits.length < limit'), source('src/economy/delivery.ts', 136, 'count++')],
  },
  {
    project: 'julius', pr: 31, sha: '69db32f4f508955ce0954e54ced8810b1f8c3c2c',
    name: 'learning-command-and-sections', budget: 300,
    query: 'In src/claude/note-signals.ts, what exact julius note command and section guidance does noteAsk give?',
    facts: [source('src/claude/note-signals.ts', 328, 'const SAVE'), source('src/claude/note-signals.ts', 329, 'const CLOSE')],
  },
  {
    project: 'julius', pr: 15, sha: 'e624c78d28080f94ceb7f7ec22e5c7f9e45aef1e',
    name: 'bounded-regex-settings', budget: 375,
    query: 'How does boundedMatcher set up its VM context, and how does it enforce REGEX_TIMEOUT_MS while matching?',
    facts: [source('src/search/grep.ts', 89, 'REGEX_TIMEOUT_MS = 1000'), source('src/search/grep.ts', 101, 'codeGeneration:'),
      source('src/search/grep.ts', 105, 'runInContext(context, { timeout: REGEX_TIMEOUT_MS })')],
  },
  {
    project: 'bulma', pr: 90, sha: '595a80cfc6708bde5a02c9150086d072bb2001bf',
    name: 'image-evidence-policy-and-cap', budget: 275,
    query: 'In skills/bulma/scripts/answer.py, quote the exact IMAGE_POLICY and show the cap inspect_attachments applies to selected images.',
    passages: [{ path: 'skills/bulma/scripts/answer.py', from: 85, to: 89 }],
    facts: [source('skills/bulma/scripts/answer.py', 105, 'len(selected) < 4')],
  },
  {
    project: 'bulma', pr: 77, sha: '9e60519a2ae8ffa4481f9909ed57dea5eeb5d920',
    name: 'actions-ci-precedence', budget: 400,
    query: 'How does job_kind treat a failure on an unfinished job, and when does classify_ci let a pending rollup override a successful Actions result?',
    facts: [source('skills/bulma-code-review/scripts/gate.py', 149, 'done in FAILED'),
      source('skills/bulma-code-review/scripts/gate.py', 151, 'phase != "completed"'),
      source('skills/bulma-code-review/scripts/gate.py', 208, 'result in {"success", "unknown", "unverified"}')],
  },
];

export function historicalCases(juliusRepo, bulmaRepo, sample = false) {
  const repositories = { julius: resolve(juliusRepo), bulma: resolve(bulmaRepo) };
  const fixtures = sample === 'marginal' ? marginalHoldout : sample ? holdout : manifest;
  return fixtures.map(fixture => {
    const repo = repositories[fixture.project];
    const read = path => execFileSync('git', ['-C', repo, 'show', `${fixture.sha}:${path}`], { encoding: 'utf8', env: { ...process.env, GIT_NO_LAZY_FETCH: '1' } });
    const facts = (fixture.facts ?? []).map(({ path, line, contains }) => {
      const rows = read(path).split('\n');
      const text = rows[line - 1];
      assert.ok(text?.includes(contains), `Invalid oracle ${fixture.project}#${fixture.pr} ${path}:${line}`);
      const repeated = rows.filter(row => row === text).length > 1;
      return { path, line, text, ...(repeated ? { previous: rows[line - 2], following: rows[line] } : {}) };
    });
    for (const { path, from, to } of fixture.passages ?? []) {
      const lines = read(path).split('\n').slice(from - 1, to);
      assert.equal(lines.length, to - from + 1);
      for (let index = 0; index < lines.length; index++) {
        if (lines[index].trim()) facts.push({ path, line: from + index, text: lines[index] });
      }
    }
    return { ...fixture, repo, facts, historical: true, holdout: Boolean(sample) };
  });
}
