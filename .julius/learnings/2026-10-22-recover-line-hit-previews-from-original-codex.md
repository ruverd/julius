---
title: Recover line-hit previews from original bytes
author: Codex
date: 2026-10-22
id: l-2cb4721f
branch: fix/recovery-impact-release
touches:
  - scripts/experiments/local-comparison.mjs
  - src/economy/index.ts
  - src/search/grep-cli.ts
---

## Decided
Sequential recovery in scripts/experiments/local-comparison.mjs restarts context.read at zero for envelopes exposing hits, because matching-line previews can be trimmed or disjoint. Only contiguous byte prefixes can be joined with a recovered suffix. Both paths verify the original object's SHA-256 digest. Keep complete reads explicit and respect supplied budgets.

## Tried and ruled out
sharedPaths: true.

## Watch out
Rebase onto current main before publishing: 0.24.0 changed literal selection and dependencies after the earlier benchmark. Rebuild and rerun the frozen comparison for the release candidate rather than advertising earlier checkout numbers as current. Preserve all identity/provenance fields in grouped impact reports and every source path in compact search. Use explicit GitHub repository selection; tags trigger the existing npm OIDC release workflow.
