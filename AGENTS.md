# Julius engineering rules

All documentation, code identifiers, CLI output, and commit messages must be in English.
Never label estimates as provider measurements. Unknown values are null, not zero.
Preserve negative savings. Never run an external operation twice for measurement.
Reports must remain offline. Optimizing must never send a model request.
User-approved stack change (September 21, 2026): use Python for the product core and Rust for performance-sensitive processing. This supersedes the initial Bun/TypeScript core plan.
Use Pydantic for runtime schemas, SQLite WAL for persistence, and PyO3/Maturin for Rust integration. Keep TypeScript only where useful for the dashboard or Bulma SDK.
Read `docs/plans/2026-09-21-stack-migration.md` before continuing implementation. The initial TypeScript reference is preserved in commit 3616024; Python/Rust is the active product core.
Keep adapters honest: fixture tests do not establish live client compatibility.
Validate Python with pytest, Ruff, and mypy, and Rust with cargo test. Build wheels with Maturin and smoke-test an isolated wheel install. Use `sh scripts/dev.sh test` for the local suite. Documentation-only changes do not require runtime tests.
Do not modify another worker's owned files without coordinating.
