# Validation and release gates

This records implementation evidence, not an agent benchmark claim.

Final local result: 44 Python tests passed, Rust workspace tests passed, Ruff passed, mypy checked 17 source files without errors, and the rebuilt stable-ABI wheel passed isolated installation and offline CLI smoke tests.

## Active Python/Rust validation

```sh
sh scripts/dev.sh setup
sh scripts/dev.sh test
sh scripts/dev.sh build
uv run --no-sync python scripts/wheel_smoke.py dist/wheels/<matching-wheel>.whl
```

The setup installs locked dependencies and builds the editable PyO3 extension. The test command runs pytest, Ruff, mypy, and Rust workspace tests. The wheel smoke installs a built artifact into a new environment outside the source tree and exercises native import, repeated import, 7,000 marginal reduction, unknown money, optimization/restoration, and HTML/CSV export.

Tests cover strict Pydantic validation (including boolean counters), explicit aliases and conflicting observations, atomic batch rollback, reconciliation, retry identity, immutable shared budget limits, multiprocess reservations, crash expiry, timestamp windows, isolated artifacts, content integrity, lexical snapshot retrieval, provider normalization, conservative imports, price validity, protected content, native reduction, and offline CLI behavior.

`tests/fixtures` freezes event and optimization contracts from the initial TypeScript checkpoint `3616024`. Python and native Rust match its optimization receipts and aggregate report for the selected corpus. The historical TypeScript suite passed 51 tests before cutover; this is reference evidence, not an active second implementation.

## Platform evidence

Local environment: macOS arm64, Python 3.12.10, Rust 1.98.1, PyO3 0.29.2, SQLite WAL/FTS5. Maturin produces a Python 3.11+ stable ABI macOS arm64 wheel. Its isolated installation was tested with Python 3.12. ABI compatibility metadata does not certify every supported interpreter or operating system.

Linux and macOS CI jobs are configured but have not run remotely in this task. WSL and native Windows remain uncertified. Wheels are unsigned development artifacts. Standalone executables, clean-machine signed installers, updates, and rollback remain release work.

Local discovery found Claude Code 2.1.278 and codex-cli 0.154.0. Version probes passed; real usage capture and rewriting were not tested. Ollama at `127.0.0.1:11434` did not respond. Provider/client parsing tests use fixtures and do not certify installed integrations.

## Open quality gates

- Two live clients must pass non-destructive official-interface usage tests with exact versions and coverage limitations.
- A live runtime test must verify installed/loaded state without inferring hardware fitness.
- A task benchmark must freeze snapshots, success criteria, model/runtime versions, cache state, and valid baseline configurations.
- Evaluation must include Portuguese/English tasks, failures, retries, overhead, latency, and confidence intervals.
- The 20% reduction target remains a hypothesis. Local text reduction and [native operation timing](native-benchmark.md) do not prove agent quality or superiority to another product.

## Technical sources

- [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
- [Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Claude Code hooks](https://code.claude.com/docs/en/hooks)
- [Codex hooks](https://developers.openai.com/codex/hooks)
- [Ollama installed models](https://docs.ollama.com/api/tags)
- [Ollama loaded models](https://docs.ollama.com/api/ps)
- [Maturin configuration](https://www.maturin.rs/config)
- [PyO3 guide](https://pyo3.rs/main/)

Consult official contracts again when implementing native integrations. Documentation alone is not compatibility certification.
