---
title: "Exact PageRank buffers, smaller output and current source evidence"
author: Codex
date: 2026-10-30
id: l-b53e7cfd
branch: feat/agent-ab-harness
touches:
  - src/ask/graphrank.ts
  - src/ask/ask.ts
  - src/graph/load.ts
  - test/query-optimization.test.ts
---

## Decided
Retain TypeScript changes in docs/strategy/query-optimization/README.md: numeric PageRank buffers for 256+ nodes, original sparse walk below; remove descriptions only when duplicated verbatim in the same code excerpt; exclude stale summaries/crux from query evidence; strengthen graph/index cache identity and read-race checks. Existing working changes preserved. Build and full suite with four test workers passed: 1578 tests, one skipped.
## Tried and ruled out
Dense-only regressed Commander; keep its sparse path. Final warm Julius median 14.24 to 9.62 ms; larger fixture 90.48 to 55.54 ms. Exact scores/order preserved against frozen reference on 300 graph cases and 432 full-result scenarios. Real MCP traffic counts fell 100085 to 97442 cl100k_base tokens; alternating confirmation agreed at 2.64% reduction. No code evidence discarded. New stale-code, cache-replacement and duplicate-output tests fail on old code and pass on new.
## Watch out
Do not claim global MCP acceleration: integration latency remained noisy and regressed in some cases. Cold CLI also has regressions. Default full suite hit an old 2-second upkeep timing assertion; isolated and bounded full reruns passed. Local counts are not provider usage or task success. Branch-wide learning check is truncated and flags old A/B reports. No commit, push or release.
