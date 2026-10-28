---
title: Reuse lazy lexical field maps by immutable loader identity
author: Codex
date: 2026-10-28
id: l-a22592c9
branch: perf/cache-lexical-field-maps
touches:
  - src/ask/ask.ts
  - src/ask/prepared-index.ts
  - test/prepared-ask-index.test.ts
---

## Decided
Cache document lookups by immutable AskIndex identity and field maps by immutable AskIndexDoc identity with WeakMaps. Prepare fields after sidecar validation and scope filtering; rebuilds replace loader identities. Ranking, output and disk formats remain unchanged. Self-contained benchmark and raw results: docs/strategy/lexical-cache-benchmark.md. On one corpus, 230 full-result comparisons passed and warm median query time decreased 27.4%, at approximately 4.9 MiB extra retained heap. Build and 1541 tests passed; one skipped.
## Tried and ruled out
Eager postings added first-query work, so exclude them from this change. Do not interpret query latency as agent speed or payload estimates as provider savings. Local cold measurements vary; claim no cold-start speedup.
## Watch out
Loader-owned sidecar documents must remain immutable. WeakMap fields must be created lazily so a narrow first query does not allocate maps for unrelated documents. A cache must not bypass stale-index validation or survive loader identity replacement. Performance evidence is one-machine and one-corpus, not a general guarantee.
