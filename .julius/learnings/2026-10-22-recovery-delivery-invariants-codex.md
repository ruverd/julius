---
title: Recovery delivery invariants
author: Codex
date: 2026-10-22
id: l-ae34bf07
replaces: l-47e7c985
branch: main
touches:
  - src/economy/index.ts
  - src/mcp/compact.ts
  - src/mcp/tools.ts
  - src/search/grep-cli.ts
  - src/investigation/index.ts
  - scripts/experiments/local-comparison.mjs
---

## Decided
Economy.read in src/economy/index.ts supports complete ranges with original digest and offsets because repeated pages inflate recovery traffic. Explicit budgets remain binding. deliverInvestigation groups all identities and shared provenance before selecting partial evidence. Exact excerpts stay under the full-report handle. formatGrepResult retains each symbol's path while shortening singleton spans and incoming-edge labels.

## Tried and ruled out
sharedPaths: true.

## Watch out
The earlier notes' intermediate 81,099-token result did not reject complete reads; formatting also needed compaction. julius check matched generic words in those notes against unrelated documentation. Those conflicts were false positives: complete-read support and per-symbol paths are preserved.
Sequential benchmark recovery explicitly requests complete delivery after the initial preview. Initial no-hint requests stay unchanged. Count discovery and recovery traffic. These scripted trials measure neither autonomous model decisions nor provider usage. Unknown counts stay null. Explicit grouped IDs preserve nonstandard identities; omitted excerpts and omitted identities are separate fields.
