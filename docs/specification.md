# Julius product and engineering specification

Source: user-provided proposal dated September 21, 2026. This repository implements the proposal incrementally; it does not claim benchmark results or universal client support.

## Product boundary

Julius is a standalone local product for context optimization and auditable usage accounting. It is not a coding agent, inference runtime, or workflow orchestrator. Locally installed clients may process data remotely. Input reduction, modeled financial savings, and subscription usage are separate concepts.

## Invariants

- Evidence and scope are independent dimensions. Provider-reported usage never proves a counterfactual baseline.
- Unknown measurements and prices remain unavailable. Negative gains remain visible.
- Only sent requests count toward realized direct reduction; optimization previews are candidates.
- Transform chains record lineage and marginal deltas without double counting.
- Preserve instructions, permissions, protocol identity, opaque data, errors, and approval flow.
- Auxiliary calls, retries, restoration, and local work belong in accounting once each.
- Originals are project-scoped, size-limited, expiring, removable, and recoverable only when authorized.
- Reconciliation appends history and supersedes prior effective measurements explicitly.
- Shared budgets require atomic reservations. Policy failure never authorizes unrestricted execution.
- Reports and exports require no model. Content and credentials are excluded from aggregate exports.
- No OAuth reuse, TLS interception, root certificates, external telemetry, or implicit model downloads.

## Architecture

User-approved revision on September 21, 2026: a modular Python monolith with Rust components for performance-sensitive processing replaces the initial Bun/TypeScript core proposal. Pydantic validates external data; PyO3 and Maturin provide the native extension boundary. SQLite WAL stores events and metadata, filesystem artifacts retain originals, and FTS5 supports optional recovery. CLI and SDK call policy, optimizer, ledger, adapters, and reporting. TypeScript remains eligible for the dashboard and Bulma SDK. Observe mode does not need a daemon. Initial dashboard is a standalone HTML export, avoiding a network listener.

Package Python with platform-specific native wheels first; independently installable executables remain a distribution milestone requiring platform tests. Python supports AI experimentation and integration; performance improvements must be measured, not inferred from the language choice. See `docs/plans/2026-09-21-stack-migration.md` for the transition sequence.

## Milestones

A: validated event ledger, observe/safe profiles, deterministic reversible reduction, usage import, runtime discovery, savings/doctor/export, and actual client compatibility tests.
B: platform distribution and signing, updates/rollback, retention, accessible dashboard, concurrency and privacy validation.
C: lexical/symbol retrieval, versioned memory, cache-aware selection, task quality benchmarks.
D: eligible model routing, hardware/resource consent, fully accounted auxiliary decisions, optional Jev shadow mode.
E: versioned Bulma SDK/stdio integration with one persistence owner and shared IDs/budgets.

## Acceptance cases

10,000 → 4,000 → 3,000 reports 7,000 reduction. Unknown model means unknown money. Interrupted streams remain incomplete. Explicit proxy/log identity counts once; distinct retries count separately. Existing transformations require explicit composition. Cross-project artifacts and expired originals cannot be restored. Expired policies and exhausted budgets deny. Observed usage and estimates retain provenance. Warm-cache economics may reject compression. Strategies with quality regressions require audited suspension. Removing an installed integration must restore its prior configuration.

## Release truthfulness

No release may claim all milestones complete from unit tests. Two real client/version tests, a live runtime test, signed distributions, and paired quality experiments are explicit release gates. Targets of 20% input reduction are goals, not results. Client and provider contracts must be checked against official documentation before integration.
