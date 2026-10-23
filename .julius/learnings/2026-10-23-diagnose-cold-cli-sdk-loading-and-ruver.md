---
title: Diagnose cold CLI SDK loading and investigation rebuilds
author: Ruver
date: 2026-10-23
id: l-a4b74c36
branch: main
touches:
  - docs/superpowers/plans/2026-10-22-selective-delivery.md
  - src/engine.ts
  - src/ai/llm/factory.ts
  - src/investigation/index.ts
  - src/economy/index.ts
---

## Decided
At runtime revision 5c28877, a local CLI module-load probe for --version recorded 626 loads across 610 unique URLs, including 207 Anthropic SDK and 154 OpenAI SDK modules. src/engine.ts imports src/ai/llm/factory.ts eagerly; the factory imports adapters that load both SDKs. Defer SDK runtime loading until AI model construction before attempting broad algorithm changes. src/investigation/index.ts execute also rebuilds on !knownSnapshot, which comes from process-local report-cache keys. A cold probe rewrote wiring, ask index and fingerprint files and counted 73 readFileSync calls versus 20 on repeated verified reports. Separate graph verification state from report caching while preserving content/configuration/extractor validation and mutation checks.

## Tried and ruled out
Removing julius_discover: discovery measured about 0.3 ms and was not the dominant extra cost.

## Watch out
src/economy/index.ts lazily constructs cl100k_base once per process; a component probe measured about 43 ms, with warm encodes far smaller. Prewarming alone moves cost rather than reducing it. deliverInvestigation encodes the same grouped JSON twice; a measured duplicate cost about 0.5 ms, a secondary optimization. Economy.record performs synchronous safe-directory checks, event writes and atomic renames. Keep exact counts, budget caps, recovery integrity, accounting and atomicity. Local probes had severe I/O noise and do not establish production speedups. Diagnostic report and raw probes are under /tmp/julius-latency-diagnosis/diagnosis.md. No runtime fix or README timing table was added.
