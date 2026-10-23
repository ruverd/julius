---
title: Reuse verified indexes and defer provider SDK startup
author: Ruver
date: 2026-10-23
id: l-28a8f56a
branch: perf/cold-start-index-reuse
touches:
  - src/engine.ts
  - src/graph/build.ts
  - src/graph/fingerprint.ts
  - src/graph/write.ts
  - src/graph/provenance.ts
  - src/investigation/index.ts
  - scripts/experiments/index-profile.mjs
---

## Decided
Load the model factory inside the engine ChatModel.create boundary. Share pending initialization and clear a rejected initialization promise. Keep adapter factories synchronous and preserve injected clients and ESM SDK error identity. Structural CLI and MCP imports must succeed when provider SDK imports are blocked.

Persist verification that binds canonical stored graph contents, resolution configuration, extractor identity, full source hashes, and explicit directory scope. Check source/configuration validity before loading stale graph bytes. Reuse that proof independently of report-cache presence. Keep a bounded in-process proof cache for freshly built indexes that cannot be certified across processes. Require fresh verification for legacy indexes; omit persistent verification for LSP enrichment, parser fallback, or missing extractor identity. Preserve before/after snapshot checks and evidence equality.

## Tried and ruled out
CommonJS lazy SDK loading changes error class identity relative to ESM imports. Defer the engine factory import instead. Using process-local report-cache presence as indexing provenance forces needless first-request rebuilds. Moving parser initialization out of the first request moves work to the first edit; measure a second edit too.

## Watch out
The local synthetic profile in docs/strategy/cold-start-validation.json used three alternating repetitions, prebuilt indexes, two edits, offline guards, and identical evidence hashes. First investigation median was 119.4 ms before and 46.4 ms after; first edit included deferred native initialization, while second-edit medians were equivalent. Warm medians were 28.4 and 29.2 ms. These are local diagnostic timings, not agent or production speed claims. Keep timing tables out of the README benchmark at the user's request. Provider usage remains null without actual measurements. Ignore text may change when the build adds its own cache rule; validate exact source/config membership and retain full ignore text in investigation snapshots.
