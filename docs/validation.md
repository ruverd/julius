# Validation and release gates

This records implementation evidence, not an agent benchmark claim.

Current local result: 247 Python tests passed, Rust workspace tests passed, Ruff passed, and mypy checked 43 source files without errors. A freshly built macOS arm64 stable-ABI wheel passed isolated installation and offline CLI smoke tests with Python 3.12.10.

## Active Python/Rust validation

```sh
sh scripts/dev.sh setup
sh scripts/dev.sh test
sh scripts/dev.sh build
uv run --no-sync python scripts/wheel_smoke.py dist/wheels/<matching-wheel>.whl
```

The setup installs locked dependencies and builds the editable PyO3 extension. The test command runs pytest, Ruff, mypy, and Rust workspace tests. The wheel smoke installs a built artifact into a new environment outside the source tree and exercises native and optional-module imports, repeated import, 7,000 marginal reduction, unknown money, optimization/restoration, and HTML/CSV export.

Tests cover strict Pydantic validation (including boolean counters), explicit aliases and conflicting observations, atomic batch rollback, reconciliation, retry identity, immutable shared budget limits, multiprocess reservations, crash expiry, timestamp windows, isolated artifacts, content integrity, lexical snapshot retrieval, provider normalization, conservative imports, price validity, protected content, native reduction, and offline CLI behavior. New fixtures exercise xAI Responses request preservation, both documented usage shapes, provider charge ticks, incomplete responses, a bounded restore function loop with each provider attempt recorded, safe candidate preparation, Jev Choice shadow fallback and auxiliary accounting, task economics with interrupted calls and chained transforms, read-only client capability reporting, the versioned stdio interface, paired bootstrap intervals, Claude/Codex hook responses, project-scoped MCP recovery, reversible managed project setup, private endpoint-scoped model snapshots and local scans, offline frozen-fixture attempt replay, scoped quality-suspension decisions, accessible local HTML filters, and cache-aware policy. A local subprocess test connects the Claude hook CLI to the recovery CLI. These are fixture tests, not live provider calls or an agent benchmark.

`tests/fixtures` freezes event and optimization contracts from the initial TypeScript checkpoint `3616024`. Python and native Rust match its optimization receipts and the prior aggregate-report fields for the selected corpus; newer report evidence fields are additive. The historical TypeScript suite passed 51 tests before cutover; this is reference evidence, not an active second implementation.

## Platform evidence

Local environment: macOS arm64, Python 3.12.10, Rust 1.98.1, PyO3 0.29.2, SQLite WAL/FTS5. Maturin produces a Python 3.11+ stable ABI macOS arm64 wheel. Its isolated installation was tested with Python 3.12. ABI compatibility metadata does not certify every supported interpreter or operating system.

Linux and macOS CI jobs are configured but have not run remotely in this task. WSL and native Windows remain uncertified. Wheels are unsigned development artifacts. Standalone executables, clean-machine signed installers, updates, and rollback remain release work.

Local discovery found Claude Code 2.1.278 and codex-cli 0.154.0. The `doctor` local protocol probe passed hook candidate, MCP initialize, tool listing, and exact artifact restore in Julius subprocesses. Separate [live Claude fixtures](live-claude-validation.md) confirmed Claude called recovery, consumed a Bash hook candidate and restored its matching original, and produced one task-attributed session usage event through bounded print mode. A [live Codex probe](codex-live-probe.md) confirmed one synthetic `turn.completed.usage` JSONL record in a read-only temporary directory. These verify narrow capabilities on exact versions; they do not provide sent-request savings, task-quality evidence, or universal client coverage. Ollama at `127.0.0.1:11434` and LM Studio at `127.0.0.1:1234` did not respond.

A prior read-only `claude --mcp-config <temporary-file> mcp get julius-recovery` probe returned `not configured` (exit 1). The later live session superseded that inconclusive check: it connected to the temporary MCP server and called its recovery tool. Four bounded Claude model calls were made with synthetic input; one failed with a provider safeguard error and is retained in the [live evidence](live-claude-validation.md).

No live xAI request was made during this validation. A single live TypeSafe Choice gateway request with synthetic state succeeded: it returned `compress`, confidence `0.77`, 373 input tokens, 31 output tokens, and actual model `jev-1.13.0`. No price was configured, so dollar cost remained unavailable. This verifies the gateway's current wire shape for that one account and request, not task quality, calibrated confidence, or active Jev decisions. Jev remains shadow-only in Julius. The xAI adapter has no measured input or output savings; its provider charge field is recognized from the documented response shape, but actual account billing has not been reconciled. Safe xAI dispatch remains experimental pending a live function-call, restoration, and quality test.

## Open quality gates

- Two live clients must pass non-destructive official-interface usage tests with exact versions and coverage limitations.
- A live runtime test must verify installed/loaded state without inferring hardware fitness.
- A task benchmark must freeze snapshots, success criteria, model/runtime versions, cache state, and valid baseline configurations.
- End-to-end evaluation must include Portuguese/English tasks, failures, retries, overhead, latency, and confidence intervals. The offline analyzer calculates intervals from caller-supplied trials; no task corpus or result exists yet.
- The 20% reduction target remains a hypothesis. Local text reduction and [native operation timing](native-benchmark.md) do not prove agent quality or superiority to another product.

## Technical sources

- [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
- [Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Claude Code hooks](https://code.claude.com/docs/en/hooks)
- [Codex hooks](https://developers.openai.com/codex/hooks)
- [Ollama installed models](https://docs.ollama.com/api/tags)
- [Ollama loaded models](https://docs.ollama.com/api/ps)
- [LM Studio native model listing](https://lmstudio.ai/docs/developer/rest/list)
- [Maturin configuration](https://www.maturin.rs/config)
- [PyO3 guide](https://pyo3.rs/main/)
- [xAI Responses API](https://docs.x.ai/developers/rest-api-reference/inference/responses)
- [xAI cost tracking](https://docs.x.ai/developers/cost-tracking)
- [TypeSafe API reference](https://docs.typesafe.ai/api)

Consult official contracts again when implementing native integrations. Documentation alone is not compatibility certification.
