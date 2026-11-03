---
title: Rust extraction pilot improves full builds while queries stay unchanged
author: Codex
date: 2026-11-03
id: l-1d5a3531
branch: feat/agent-ab-harness
touches:
  - scripts/experiments/rust-extractor/src/lib.rs
  - scripts/experiments/rust-extractor/pilot.mjs
  - docs/strategy/rust-extractor/README.md
---

## Decided
User requested an isolated hybrid Rust extractor experiment while keeping CLI/MCP and orchestration in TypeScript. Report: docs/strategy/rust-extractor/README.md. Opt-in Node-API cdylib handles TypeScript/TSX/JavaScript structural extraction using the C core/grammars shipped by the same installed Tree-sitter npm packages. Existing TypeScript materializes bodies, signatures and hashes, resolves edges, writes the index/cards and ranks queries. Production source and npm dependencies were unchanged. Four rotated rounds: Julius complete indexing 1389.48 to 484.73 ms (2.87x), peak RSS 266.2 to 164.3 MiB; Commander 125.27 to 61.03 ms; generated 13010-node fixture 2430.56 to 1031.82 ms. Whole-worker gains include startup and are smaller. Exact equality passed 1223 extraction cases including repeated boundary fixtures, 60 graph/index phase pairs and 304 paired full-query checks, plus actual CLI/MCP evidence. Full baseline and native validation npm test suites each passed 1585 tests with one skip; three native-boundary tests passed. Artifacts include source/runtime/native hashes and complete compressed test logs.
## Tried and ruled out
Do not promote this prototype or infer a full-engine rewrite payoff. Warm Julius API remained 5.80 ms; the extractor does not run on unchanged indexed queries. Incremental work stays close to baseline and full-build RSS gains do not generalize to daemon memory. Initial aggregate gate failed on Commander unchanged rebuild latency, 60.44 to 73.55 ms (21.7% regression). Twelve additional fresh workers per arm after tests exited gave 77.50 to 78.54 ms (1.35% regression); retain initial failure instead of replacing it. First discarded harness loaded Rust in baseline and shared cumulative RSS across phases; corrected valid run avoids both. Initial baseline test failure was missing Git metadata in a disposable snapshot; full rerun passed after initializing only disposable repositories.
## Watch out
Single Apple M4 Pro, Node 22.23.2, Rust 1.99.1 release, OS cache/load uncontrolled. Fixture is repetitive and Commander is an installed-source subset. Prototype declares a small C/Node-API ABI directly; future production work needs typechecked contracts, deliberate backend/cache versioning, failure/resource limits, platform packaging, fallback behavior and held-out real repositories. Offline benchmark guard logs stayed empty; Cargo used cached dependencies with --offline. No model/provider/agent-success measurement, commit, push, install or release. Branch-wide julius check had 20 heuristic conflicts in pre-existing files and a 400KB diff limit; untracked experiment files were excluded. Do not call that a clean review.
