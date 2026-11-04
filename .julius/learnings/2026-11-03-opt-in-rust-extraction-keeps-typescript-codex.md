---
title: Opt-in Rust extraction keeps TypeScript fallback and backend-scoped reuse
author: Codex
date: 2026-11-03
id: l-2e3591a7
branch: feat/hybrid-rust-extractor
touches:
  - src/graph/rust.ts
  - src/graph/rust-settings.ts
  - src/graph/extract-cache.ts
  - native/extractor/src/lib.rs
  - docs/hybrid-extractor.md
---

## Decided
User authorized continuing the hybrid extractor and opening a PR. Add an opt-in integration on a clean branch from main; keep TypeScript default. Explicit npm run build:native uses locked offline Cargo inputs unless --online is requested. Ship Rust source, not a platform binary; preserve existing native/WASM CI and add Linux/macOS Rust lanes. CLI/MCP stay TypeScript. Native protocol validates compact tuples before materialization, with source/depth/node limits and TypeScript fallback. Capture the executable override before CLI dotenv loads repository settings.
## Tried and ruled out
The earlier isolated-only pilot restriction is superseded by explicit user authorization for this opt-in follow-up, not permission to enable Rust by default or rewrite the whole engine. Preserve the initial failed incremental gate and targeted repeat. Do not reuse cached parses across backend/binary identities. Unexpected native/protocol failures disable persistent provenance in that process. Normal operations never build/download Rust. Native process crashes cannot be recovered by JavaScript.
## Watch out
Backend identity includes loaded binary SHA-256. Restart MCP after rebuilding. The old 2.87x number measures the archived pilot, not this integration or agent speed. Native paths from repository .env must not select executable code. Inherited upkeep-hook wall-clock assertions can fail under machine contention; runner now forwards explicit Node test flags so suites can cap concurrency without changing defaults. julius check reports lexical matches in retained diagnostics, limits and regression fixtures; explain them instead of deleting evidence. No provider savings claim; default offline behavior stays intact.
