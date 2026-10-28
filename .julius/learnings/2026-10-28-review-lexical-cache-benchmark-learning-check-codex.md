---
title: Review lexical cache benchmark learning-check matches
author: Codex
date: 2026-10-28
id: l-8720d895
branch: perf/cache-lexical-field-maps
touches:
  - src/ask/ask.ts
  - src/ask/prepared-index.ts
  - docs/strategy/lexical-cache-benchmark.md
---

## Decided
Review accepts 15 lexical check findings around src/ask/ask.ts and preparedAskDocs with explicit commit and PR rationale. JSON scope denies provider usage and agent-speed claims; stored queries are test inputs. The benchmark reconstructs local ESM field allocation, without loading provider SDKs or changing error-class identity. The integration test invalidates the loader after rebuild; prepared-cache presence never substitutes for indexing provenance. Documentation excludes eager postings rather than restoring them.
## Tried and ruled out
Deleting negative disclaimers, query fixtures or regression checks to appease keyword matches would hide useful evidence. Keep correct data and behavior, following Ruver's semantic-review learnings.
## Watch out
Only lexical field allocation is cached. Complete result equality, loader invalidation, unmodified sidecars and regression tests support this change. Timings are local retrieval diagnostics. Provider usage stays null and retained-memory costs remain disclosed. These exceptions do not authorize ranking, provenance-verification or billing changes.
