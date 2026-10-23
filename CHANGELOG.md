# Changelog

Julius releases follow [Semantic Versioning](https://semver.org/).
The unchanged upstream history is in [upstream-changelog.md](docs/upstream-changelog.md).

## [Unreleased]

## 0.24.1

### Fixed

- Honor complete delivery for retained context byte ranges while preserving explicit budgets and original-object integrity.
- Return complete impact identity indexes with shared provenance before falling back to partial detailed evidence.
- Reduce repeated span and incoming-edge notation in MCP search while retaining every symbol's source location.

### Changed

- Refresh README benchmark evidence against the release candidate: 235,134 versus 463,332 protocol tokens across ten synthetic task types, including discovery, invocation and exact-byte recovery traffic.
- Record 78,291 tokens for no-hint recovery and 13,062 for composed impact, below the corresponding upstream aggregates; retain the per-language Python recovery regression.
- Retain source coverage, uncertainty and detailed investigation reports for follow-up retrieval.

Benchmark results are offline protocol counts, not provider token usage, billing or coding accuracy.

## 0.24.0

### Added

- First public npm distribution of `@ruverd/julius`, with the `julius` executable and `Julius` API.
- Compact MCP discovery, local change-impact and failure-localization investigations.
- Recoverable context delivery with explicit budgets, literal focus and complete retrieval.
- Transactional MCP setup for Claude Code, Cursor, Codex and the native xAI Grok CLI.
- Tag-based release automation, npm trusted publishing, package installation smoke tests and release metadata checks.

### Changed

- Keep runtime state under `.julius`, with local graph refresh and shared learnings.
- Preserve MIT licensing, upstream credits and the original changelog in every npm package.
- Publish stable versions to `latest` and alpha, beta or release candidates to `next`.
- Exclude development scripts, tests, local state and experiment traces from the npm archive.

### Fixed

- Resolve the Node entry point for `vscode-jsonrpc` in packaged installations.
- Bound selective evidence delivery at UTF-8 boundaries and distinguish missing literals from oversized matches.

This release does not measure provider token usage or billing. Recorded benchmark
results refer to the historical revision identified in the README.
