---
title: Generate README benchmarks from recorded protocol trials
author: Ruver
date: 2026-10-23
id: l-f11af059
branch: docs/benchmark-readme
touches:
  - README.md
  - docs/assets/context-benchmark.svg
  - scripts/render-readme-benchmark.mjs
  - docs/strategy/recovery-impact-comparison.json
---

## Decided
scripts/render-readme-benchmark.mjs generates the README.md headline, comparison tables, and docs/assets/context-benchmark.svg from docs/strategy/recovery-impact-comparison.json. Keep per-task results and the Python no-hint regression visible so the aggregate cannot hide weak cases. Its --check mode compares both text and chart with the report. Cross-check summary totals and evidence outcomes against raw trials before rendering.

## Tried and ruled out
Using offline protocol token reductions to claim lower provider bills, faster agents, or more solved issues. Those need matched real agent trials and provider measurements. Presentation changes do not create new experimental evidence.

## Watch out
Counts include initialization, schemas, requests, responses, and recovery. Evidence checks cover synthetic fixtures, not coding accuracy or autonomous tool selection. Link the measured source revision and retained traces. Preserve negative reductions and unknown values. Do not replace the frozen report when changing presentation.
