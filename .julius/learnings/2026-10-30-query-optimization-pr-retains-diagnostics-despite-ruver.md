---
title: Query optimization PR retains diagnostics despite learning keyword matches
author: Ruver
date: 2026-10-30
id: l-b0b86b80
branch: perf/query-speed-and-evidence
touches:
  - docs/strategy/query-optimization/README.md
  - docs/strategy/query-optimization/baseline_regressions.tap.gz
  - docs/strategy/query-optimization/bounded_suite.tap.gz
  - docs/strategy/query-optimization/change.patch
  - docs/strategy/query-optimization/default_suite.tap.gz
  - docs/strategy/query-optimization/dense-prototype/plan.json
  - docs/strategy/query-optimization/dense-prototype/report.json
  - docs/strategy/query-optimization/plan.json
  - docs/strategy/query-optimization/protocol-confirmation.json
  - docs/strategy/query-optimization/protocol-traces.json.gz
---

## Decided
Ship src/ask/graphrank.ts, src/ask/ask.ts and src/graph/load.ts on a clean branch from current main, preserving other workers' changes. Keep source evidence, exact ranking and unknown provider usage. Archive verbose experiment reports as gzip to keep the review diff small; JSON content is unchanged.

## Tried and ruled out
Deleting diagnostics to satisfy learning-check keyword matches would hide measured regressions. After staging this isolated change, julius check flags docs/strategy/query-optimization/README.md and experiment descriptions as reintroducing prohibited behavior. These are heuristic false positives: the report explicitly rejects provider-billing and agent-speed inferences, retains the sparse path after the dense-only regression, and documents existing advertised MCP dispatch. Cache file identity changes do not alter lazy SDK loading or indexing provenance. Shared-path strings in the historical patch are unchanged context, not an enabled option.

## Watch out
Source-only check passed. Run the complete staged learning check again before publishing; retain conflicts and rationale in PR description. Historical benchmark validation describes its original working tree, not subsequent main changes. New branch build and tests must be recorded separately. No Rust migration, release or production deployment is included.
