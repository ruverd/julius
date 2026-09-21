# Julius engineering rules

All documentation, code identifiers, CLI output, and commit messages must be in English.
Never label estimates as provider measurements. Unknown values are null, not zero.
Preserve negative savings. Never run an external operation twice for measurement.
Reports must remain offline. Optimizing must never send a model request.
User-approved stack change (September 21, 2026): use Python for the product core and Rust for performance-sensitive processing. This supersedes the initial Bun/TypeScript core plan.
Use Pydantic for runtime schemas, SQLite WAL for persistence, and PyO3/Maturin for Rust integration. Keep TypeScript only where useful for the dashboard or Bulma SDK.
Read `docs/plans/2026-09-21-stack-migration.md` before continuing implementation. Existing TypeScript code is a migration reference, not the target product core.
Keep adapters honest: fixture tests do not establish live client compatibility.
Validate migrated Python with pytest and configured lint/type checks, and Rust with cargo test. Until cutover, also run `bun test` and `bun run typecheck` for changes to the existing TypeScript implementation. Documentation-only changes do not require runtime tests.
Do not modify another worker's owned files without coordinating.
