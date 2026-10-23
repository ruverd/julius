---
title: Offline measurement disclaimers are not provider savings claims
author: Ruver
date: 2026-10-23
id: l-0cc612dc
branch: docs/benchmark-readme
touches:
  - README.md
  - docs/assets/context-benchmark.svg
  - scripts/render-readme-benchmark.mjs
---

## Decided
README.md and scripts/render-readme-benchmark.mjs state that provider usage, dollar cost, agent speed, and coding accuracy are unmeasured. Keep these disclaimers alongside the protocol counts. During the README redesign, julius check matched generic words in those disclaimers against the rejected approach in the preceding presentation learning. The three matches are lexical false positives: no provider saving, timing improvement, or issue-resolution claim was added. Document this check result in the PR rather than deleting measurement limits.

## Tried and ruled out
providerCost: 0.

## Watch out
The report retains null for unknown provider measurements. A presentation update reuses recorded evidence and cannot support new efficacy claims. Keep the underlying benchmark JSON unchanged.
