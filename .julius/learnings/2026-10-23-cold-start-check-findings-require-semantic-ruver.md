---
title: Cold-start check findings require semantic review
author: Ruver
date: 2026-10-23
id: l-d4e8221f
branch: perf/cold-start-index-reuse
touches:
  - CHANGELOG.md
  - scripts/experiments/index-profile.mjs
---

## Decided
The v0.24.2 check findings in CHANGELOG.md and scripts/experiments/index-profile.mjs are lexical false positives, reviewed against actual code. The changelog describes deferred ESM factory loading; adapters retain their SDK class identity. The profiling wrapper counts local Git subprocesses and appends measurement records. It does not change authentication or publish workflows. The repetition lower bound validates harness arguments. It does not modify tokenizer initialization or economy accounting. Keep those correct changes and document this exception in the PR and commit.

## Tried and ruled out
Rewriting valid code or deleting useful diagnostics to satisfy keyword matches would hide evidence without fixing a defect.

## Watch out
Inspect the cited line and surrounding operation before accepting a learning-check conflict. Regression tests, source review, and preserved evidence establish the intended behavior here.
