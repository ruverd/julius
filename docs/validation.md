# Validation and release gates

This records implementation evidence, not an agent benchmark claim.

Current local result: 366 Python tests passed on macOS arm64 and Linux arm64 in a Debian Bookworm container. Rust workspace tests, Ruff, and mypy (50 source files) passed in both environments. A freshly rebuilt macOS arm64 stable-ABI wheel passed isolated installation and offline CLI smoke tests with Python 3.12.10. A PyInstaller macOS arm64 standalone executable passed its CLI, hook/MCP, restoration, memory search, and memory audit smoke. Its archive passed preview, temporary managed install, launch, removal, and repeated-removal checks. The optional Linux arm64 container run passed the source checks, standalone smoke, and archive checks. Both builds include the current tokenizer-provenance, cost-attribution, artifact-export, benchmark-adherence, exact-version capability manifest, task-dashboard, and journaled-installer additions.

## Active Python/Rust validation

```sh
sh scripts/dev.sh setup
sh scripts/dev.sh test
sh scripts/dev.sh build
uv run --no-sync python scripts/wheel_smoke.py dist/wheels/<matching-wheel>.whl
```

The setup installs locked dependencies and builds the editable PyO3 extension. The test command runs pytest, Ruff, mypy, and Rust workspace tests. The wheel smoke installs a built artifact into a new environment outside the source tree and exercises native and optional-module imports, repeated import, 7,000 marginal reduction, unknown money, optimization/restoration, and HTML/CSV export.

Tests cover strict Pydantic validation (including boolean counters), explicit aliases and conflicting observations, tokenizer identity and append-only reconciliation, atomic batch rollback, retry identity, immutable shared budget limits, multiprocess reservations, crash expiry, timestamp windows, isolated artifacts, content integrity, lexical snapshot and code-symbol retrieval, provider normalization, conservative imports, price validity, protected content, native reduction, and offline CLI behavior. New fixtures exercise xAI Responses request preservation, both documented usage shapes, provider charge ticks, incomplete responses, a bounded restore function loop with each provider attempt recorded, safe candidate preparation, sent-response acknowledgement without complete usage, refusal to recompress a known Julius marker without lineage, Jev Choice shadow fallback and auxiliary accounting, task economics with interrupted calls and chained transforms, strict output counter comparability and provenance, signed compression/routing attribution for modeled uncached input cost, read-only client capability reporting, the versioned stdio interface, paired bootstrap intervals, Claude/Codex hook responses, project-scoped MCP recovery, reversible managed project setup, private endpoint-scoped model snapshots and local scans, scoped memory audit/pagination, offline frozen-fixture attempt replay and protocol registration with modality-specific arms, trusted subprocess checks, scoped quality-suspension decisions, accessible local HTML filters, cache-aware policy, replayable filtered event export, report coverage/cost provenance, daily dashboard series with separate request/tool-output reductions, category decomposition, and offline model-route eligibility. A local subprocess test connects the Claude hook CLI to the recovery CLI. A second subprocess test covers the Julius-side Bulma stdio contract without Bulma adoption. A loopback HTTP server tests xAI request preservation and fail-closed response handling through the real urllib transport; this is a local protocol fixture, not a live xAI call or an agent benchmark.

`tests/fixtures` freezes event and optimization contracts from the initial TypeScript checkpoint `3616024`. Python and native Rust match its optimization receipts and the prior aggregate-report fields for the selected corpus; newer report evidence fields are additive. The historical TypeScript suite passed 51 tests before cutover; this is reference evidence, not an active second implementation.

The current suite additionally checks that session-delta usage never inflates request coverage, even with a request ID; that explicit artifact export defaults to metadata, requires raw-content opt-in, preserves project and expiration boundaries, and rejects unsafe destination paths; and that a benchmark adherence audit rejects missing, excess, misordered, or metadata-inconsistent attempt records. These are local contract checks. They do not supply independently observed task outcomes or a quality comparison.

Installer tests now inject interrupted update and removal transactions and verify recovery or refusal when a required backup is missing. The HTML task table has code-level checks for local filters and visible-row CSV export; one generated local report was opened and rendered in Chrome, but filter and download behavior have not received a full browser acceptance test. `doctor` produced an exact-version capability manifest for the detected Claude Code and Codex versions and passed Julius's local hook/MCP probe; it did not invoke either client. The archive smoke script resolves its macOS temporary prefix before strict symlink checks because `/var` is a symlink to `/private/var` on that host.

## Platform evidence

Local environment: macOS arm64, Python 3.12.10, Rust 1.98.1, PyO3 0.29.2, SQLite WAL/FTS5. Maturin produces a Python 3.11+ stable ABI macOS arm64 wheel. Its isolated installation was tested with Python 3.12. ABI compatibility metadata does not certify every supported interpreter or operating system.

Linux and macOS CI jobs are configured but have not run remotely in this task. The [Linux arm64 container script](../scripts/linux_container_smoke.sh) passed on Debian Bookworm/glibc 2.36 with Python 3.11.2 and Rust 1.98, built a wheel and standalone archive, then completed temporary install/remove. It does not certify native Linux hosts, other distributions/architectures, WSL, or Windows. Both local standalone archives are unsigned development artifacts. The managed archive installer has fixture-tested update/rollback and temporary install/remove smoke on both local platform environments; clean-machine signed installers and trusted updates remain release work.

Local archive SHA-256 values for this source build: macOS arm64 `c3cd2890760e55d602bc2d1fe873a832e3a6501fe9062d04160b0791202fd955`; Linux arm64 `b43239fe5919d03c8748a11e970f61315f0b6506352d1a6cd8f6e28e4d75974c`. These hashes identify the locally built bytes; they are not publisher signatures.

Local discovery found Claude Code 2.1.278 and codex-cli 0.154.0. The `doctor` local protocol probe passed hook candidate, MCP initialize, tool listing, and exact artifact restore in Julius subprocesses. Separate [live Claude fixtures](live-claude-validation.md) confirmed Claude called recovery, consumed a Bash hook candidate and restored its matching original, and produced one task-attributed session usage event through bounded print mode. One further bounded baseline/safe Claude pair completed in both arms; the safe arm's client-estimated session cost was USD 0.00358145 higher. A [live Codex probe](codex-live-probe.md) confirmed one synthetic `turn.completed.usage` JSONL record in a read-only temporary directory. These verify narrow capabilities on exact versions; they do not provide sent-request savings, task-quality evidence, or universal client coverage. Ollama at `127.0.0.1:11434` and LM Studio at `127.0.0.1:1234` did not respond.

A prior read-only `claude --mcp-config <temporary-file> mcp get julius-recovery` probe returned `not configured` (exit 1). The later live session superseded that inconclusive check: it connected to the temporary MCP server and called its recovery tool. Four bounded Claude model calls were made with synthetic input; one failed with a provider safeguard error and is retained in the [live evidence](live-claude-validation.md).

No live xAI request was made during this validation. The [loopback transport test](xai-loopback.md) confirms one HTTP POST, authorization/body preservation, usage parsing, bounded responses, and no automatic repeat on selected failures. A single live TypeSafe Choice gateway request with synthetic state succeeded: it returned `compress`, confidence `0.77`, 373 input tokens, 31 output tokens, and actual model `jev-1.13.0`. No price was configured, so dollar cost remained unavailable. This verifies the gateway's current wire shape for that one account and request, not task quality, calibrated confidence, or active Jev decisions. Jev remains shadow-only in Julius. The xAI adapter has no measured input or output savings; its provider charge field is recognized from the documented response shape, but actual account billing has not been reconciled. Safe xAI dispatch remains experimental pending a live function-call, restoration, and quality test.

## Open quality gates

- Two live clients must pass non-destructive official-interface usage tests with exact versions and coverage limitations.
- A live runtime test must verify installed/loaded state without inferring hardware fitness.
- A representative task benchmark must register frozen snapshots, criteria, model/runtime versions, cache state, and valid baseline configurations, then verify the execution matched that registration. The [offline registration module](evaluation-protocol.md) validates declared manifests and paired arm assignments but has no actual task observations.
- End-to-end evaluation must include Portuguese/English tasks, failures, retries, overhead, latency, and confidence intervals. The offline analyzer and frozen-fixture runner can produce task outcomes, but no representative corpus or causal product result exists yet. The single live Claude synthetic pair is descriptive only.
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
