# Investigations during normal conversation

After one-time MCP setup, ask Claude Code, Codex or the native xAI Grok CLI a
normal coding question. Julius's MCP instructions tell the agent to discover and
use `investigation.execute` itself. No user CLI or slash command is required for
investigation, graph creation, freshness or result recovery. Host permissions and
model tool selection still apply; no transparent interception is claimed.

## Available recipes

- `change-impact`: exact repository-relative paths, optional incoming depth
  (default 2, maximum 8). Combines file definitions, incoming graph traversal,
  deduplication, confidence provenance and source excerpts into one response.
- `failure-localization`: a literal diagnostic fragment. Searches the selected
  source snapshot and returns nearby evidence with enclosing symbols when known.
  It does not run tests or declare a proven root cause.

Both recipes run locally without another model, shell execution or network
service. They are experimental and available through the existing two MCP tools;
there is no additional per-repository activation command. Full-tools compatibility
mode retains only the inherited six tools; compact mode is required for recipes.

## Freshness and reuse

Source contents are hashed before answering, including uncommitted edits. New,
renamed and deleted sources change the snapshot. Build configuration and selected
project configuration files also participate. Graph fingerprints must match the
current source bytes. A changed snapshot rebuilds the structural graph locally;
changes observed during execution discard the answer. Failed verification returns
an error so the agent can fall back to direct inspection.

The initial cache is deliberately process-local, bounded to 32 results and 8 MiB.
Identical verified requests reuse computation within that MCP process. They still
return a self-contained answer: no assumption that an agent remembers an earlier
message. This is not persistent cross-session memory, latent communication or
automatic suppression of repeated prompt tokens. Changed source invalidates the
whole investigation rather than attempting fine-grained dependency reuse.

Selection follows the existing graph file rules. Ignored, oversized, unsupported
and excluded sources can be absent; unresolved dynamic calls remain uncertain.
Results disclose scope and missing indexed-file coverage. A zero-result answer
never establishes absence of impact. Workspace-parent investigations currently
fall back to existing federated graph tools.

## Limits and recovery

The runtime accepts at most 32 paths, 10,000 source files, 32 MiB of source/config
content, 100,000 graph nodes and 300,000 edges. Investigation traversal is capped
at 10,000 visited nodes and 500 evidence records, with a cooperative five-second
execution deadline after indexing. Filesystem enumeration, hashing and graph
indexing do not have a hard wall-time deadline. These limits are not claims of
constant memory or latency for indexing.

Small reports are returned complete. Larger reports select whole evidence records,
prioritizing dependents over seed definitions, within the requested token budget.
A retained full report can be searched or read in byte ranges through
`context.read`. Very small budgets fall back to the ordinary bounded envelope.
Execution-limit omissions cannot be recovered from that report: the agent must
narrow or repeat the investigation with different inputs. Source excerpts are
capped at 12 lines/2,000 characters and carry their original span and completeness.

The Economy ledger counts rendered delivery and retrieval. Reuse of computation
is not itself recorded as token savings. No provider billing or coding-success
claim follows from this implementation. Persistent result storage/expiry,
adaptive cost prediction, arbitrary plan composition and receiver-aware deltas
remain future work in the [delivery plan](strategy/delivery-plan.md).

## Evaluation support

`src/evaluation/index.ts` validates paired imported provider trial records and
reports total tokens, cost, success difference, coverage and cost per success.
`scripts/compare-trials.mjs` is a developer analysis entry point, not part of the
user coding workflow. Its input is a JSON array of records with:

```json
{
  "task": "impact-001",
  "taskRevision": "pinned-task-commit",
  "repetition": 0,
  "arm": "trail",
  "revision": "pinned-executable-commit",
  "host": "pinned-host-version",
  "model": "exact-model-id",
  "outcome": "pass",
  "usage": {
    "inputTokens": null,
    "cachedInputTokens": null,
    "outputTokens": null,
    "costUsd": null
  }
}
```

Every task/repetition needs both `trail` and `julius` records with matching task
revision, host and model. Each arm pins one executable revision. Input tokens
include cached input; do not add cached tokens twice. Output includes reasoning
when the provider reports reasoning as a subset. Aggregate all retries and
attempts into the run before importing; include failed and timed-out work.

Unknown observations stay null, negative savings remain negative, and incomplete
usage cannot produce a complete total. The importer trusts supplied observations;
it does not independently authenticate them, run a provider, execute upstream
Trail or calculate confidence intervals. Live matched task trials and the quality
non-inferiority gate remain unperformed. Configuration/stdio tests validate wiring,
not actual host model adoption.
