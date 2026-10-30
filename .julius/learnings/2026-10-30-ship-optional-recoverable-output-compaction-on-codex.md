---
title: Ship optional recoverable output compaction on a clean main branch
author: Codex
date: 2026-10-30
id: l-72cc4a2e
branch: feat/optional-output-compaction
touches:
  - src/economy/compact-output.ts
  - src/economy/index.ts
  - src/economy/cli.ts
  - src/mcp/compact.ts
  - test/economy-compaction.test.ts
---

## Decided
User authorized an internal opt-in implementation and requested its PR. CLI capture/run accept --compact tap|log|build; Economy accepts compact and MCP context.capture exposes the same argument. Default remains off. Original-byte handles remain authoritative. Commands execute once and select a compacted envelope only when smaller than diagnostic delivery; incomplete captures bypass compaction. Complete/focused MCP delivery takes precedence. No new dependency or release.
## Tried and ruled out
Do not transfer prototype percentages to integrated commands or provider bills. Passing names and timings may require recovery. No unchanged-latency or arbitrary semantic-equivalence claim. Keep unrelated experiments and older MCP guidance changes outside this branch.
## Watch out
Clean branch from main 1e06708: npm run build and npm test pass (1552 passed, one skipped). Five new tests cover API, CLI, MCP, budgets, binary/CRLF recovery, exit status and execution count. Learning check has eight lexical conflicts: documentation warnings match savings rules, and generic test/output/import words match unrelated PageRank, provenance and discovery notes. No SDK, index verification, ranking or discovery removal occurs; no provider cost is set to zero. Retain those warnings and explain matches in the PR.
