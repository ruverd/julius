# Julius Python and Rust Migration

Status: user-approved architecture change; Python/Rust core cutover implemented and locally validated. Cross-platform release certification remains open.
Date: September 21, 2026.

## Decision

Replace the Bun/TypeScript product core with Python and Rust. Keep the product scope, economic invariants, event provenance, and acceptance criteria unchanged. Python owns the ledger, policy, adapters, model registry, reporting, CLI, and experiments. Rust serves performance-sensitive compression and text processing through PyO3. Maturin packages the native extension. TypeScript may remain in the dashboard or Bulma SDK, communicating through versioned contracts rather than a second ledger.

This decision prioritizes the Python AI ecosystem and native processing options. It does not establish a performance advantage without measurements. Do not add AI model dependencies to reporting or require a model for offline operation.

## Coordination boundary

This document was written from a side conversation at the user's request. No active agents were contacted or interrupted, and no source files were migrated. The main implementation coordinator must reconcile worker ownership before assigning migration work. Preserve in-progress source and tests as reference material; do not delete or rewrite another worker's files during the transition.

## Target layout

- `pyproject.toml`: Python package metadata, CLI entry point, development tools, and Maturin configuration.
- `python/julius/`: product modules and a private native-extension namespace.
- `crates/julius-core/`: native compression and text-processing functions without hidden network or command execution.
- `crates/julius-py/`: narrow PyO3 binding layer.
- `tests/python/`: Python unit and integration tests.
- `tests/fixtures/`: language-neutral event and transformation fixtures.
- Existing `src/` and TypeScript tests: temporary migration references, retained until cutover.

## Ordered subtasks

1. **Checkpoint and contracts.** The main coordinator inventories current work, records passing/failing checks, and freezes JSON fixtures for the event envelope and SDK receipts. Preserve nulls, signed reductions, discriminated payloads, source IDs, and reconciliation semantics. Translate TypeScript nulls to Python None internally and JSON null at boundaries.
2. **Python packaging.** Establish the package and CLI entry point, choose supported Python versions based on dependency and wheel compatibility, and configure pytest plus lint/type checking. Verify an isolated installation and an offline CLI invocation.
3. **Ledger port.** Move event validation to strict Pydantic schemas and persistence to SQLite transactions with WAL. Port duplicate-source, conflicting-ID, reconciliation, retry, interrupted-stream, and atomic-budget tests before replacing the existing implementation. Preserve integer counter validation; reject bool values as counters.
4. **Policy and artifact port.** Port fail-closed policy checks, project isolation, symlink/traversal defenses, retention, recoverability checks, and receipts. Verify identical behavior using shared fixtures; optimizing must not send model requests.
5. **Adapters and reports.** Port provider normalization, read-only runtime discovery, CLI reports, exports, and the HTML report. Retain unknown usage and price states, independent evidence/scope dimensions, and explicit fixture-versus-live compatibility labels.
6. **Rust boundary.** Implement a substantive deterministic text-processing operation behind the established transform interface, with parity tests and representative timing/memory measurements. Keep permissions, persistence, and network execution outside the native compressor. Avoid maintaining two complete optimizer implementations.
7. **End-to-end cutover.** Exercise setup, import, optimization preview, authorized usage recording, savings, export, restoration, and expiry against temporary data. Verify 10,000 → 4,000 → 3,000 yields 7,000, unknown prices remain unavailable, retries count separately, and negative reductions remain visible. Switch documentation and CLI entry points only after these pass.
8. **Distribution and cleanup.** Build and test native wheels on declared macOS/Linux targets. Validate clean installation and removal. Remove superseded TypeScript core code only after callers migrate and equivalent acceptance tests pass. Signed standalone executables remain a separate, explicit release gate.

## Work ownership after coordinator reconciliation

The ledger, optimizer/artifacts, and adapters remain independent migration subtasks suitable for Sol workers. The primary coordinator owns packaging, cross-module contracts, reports/CLI integration, and verification. Coordinate the Rust binding boundary with the optimizer owner. Do not start new agents from this side conversation.

## Completion evidence

Record exact commands and results for Python tests, configured lint/type checks, Rust tests, wheel installation, and offline CLI smoke tests. Retain relevant TypeScript checks until cutover. Do not describe this document edit as a completed language migration, a delivered Rust speedup, or verified cross-platform support.

## Cutover record

The coordinator checkpointed the initial TypeScript product at commit `3616024`, then assigned Python ledger/events, optimizer/artifacts/Rust, and adapters/pricing to three Sol workers. Strict Pydantic schemas retain JSON contracts. Frozen outputs in `tests/fixtures` verify native optimization and report parity. Existing TypeScript-style SQLite event bodies normalize before idempotency comparison.

Python now owns the active CLI/SDK, SQLite ledger, policies, adapters, reporting, artifacts, FTS5 memory, and pricing. PyO3 exposes a substantive deterministic repeated-line operation from `julius-core`. The binding uses Python 3.11 stable ABI support. Maturin built a macOS arm64 wheel; an isolated Python 3.12 environment installed it and exercised native import, duplicate import, signed marginal arithmetic, optimization/restoration, and HTML/CSV export. TypeScript source was removed from the active tree after these checks; its checkpoint and frozen fixtures remain available.

This completes the local core migration, not the full product roadmap. Native client integrations, quality benchmarks, Linux/WSL certification, signed distributions, and managed update/rollback remain separate gates. See `docs/validation.md` for final commands and test counts.
