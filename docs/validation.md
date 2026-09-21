# Validation and release gates

This records implementation evidence, not an agent benchmark claim.

Current local result: 427 Python tests passed on macOS arm64 and Linux arm64 in a Debian Bookworm container. Rust workspace tests, Ruff, and mypy (56 source files) passed in both environments. A freshly rebuilt macOS arm64 stable-ABI wheel passed isolated installation and offline CLI smoke tests with Python 3.12.10. A PyInstaller macOS arm64 standalone executable passed its CLI, hook/MCP, Codex observe hook, frozen Jev replay, restoration, memory search, and memory audit smoke. Its archive passed preview, temporary managed install, launch, removal, and repeated-removal checks. The optional Linux arm64 container run passed the source checks, standalone smoke, and archive checks. Both builds include the frozen tiny-repository and Jev corpora, Codex hook command and probe, plus the earlier bounded Claude pilot, xAI attempt evidence, tokenizer provenance, cost attribution, artifact export, benchmark adherence, capability manifest, task dashboard, and journaled installer.

## Active Python/Rust validation

```sh
sh scripts/dev.sh setup
sh scripts/dev.sh test
sh scripts/dev.sh build
uv run --no-sync python scripts/wheel_smoke.py dist/wheels/<matching-wheel>.whl
```

The setup installs locked dependencies and builds the editable PyO3 extension. The test command runs pytest, Ruff, mypy, and Rust workspace tests. The wheel smoke installs a built artifact into a new environment outside the source tree and exercises native and optional-module imports, repeated import, 7,000 marginal reduction, unknown money, optimization/restoration, HTML/CSV export, the Codex hook no-op, and packaged Jev and repository corpora.

An installed-wheel test loads the packaged frozen repository corpus. A macOS standalone dry run selected `bug-en` with `/usr/bin/false` as the client executable: both arms correctly remained incomplete with null usage and cost, proving the bundled corpus and CLI path load without making a model call. The separate bundled gate command accepted one fixed read and denied a repeat. These checks do not show that a real client run from the standalone binary succeeds.

Tests cover strict Pydantic validation (including boolean counters), explicit aliases and conflicting observations, tokenizer identity and append-only reconciliation, atomic batch rollback, retry identity, immutable shared budget limits, multiprocess reservations, crash expiry, timestamp windows, isolated artifacts, content integrity, lexical snapshot and code-symbol retrieval, provider normalization, conservative imports, price validity, protected content, native reduction, and offline CLI behavior. New fixtures exercise xAI Responses request preservation, both documented usage shapes, provider charge ticks, incomplete responses, a bounded restore function loop with each provider attempt recorded, safe candidate preparation, sent-response acknowledgement without complete usage, refusal to recompress a known Julius marker without lineage, Jev Choice shadow fallback and auxiliary accounting, task economics with interrupted calls and chained transforms, strict output counter comparability and provenance, signed compression/routing attribution for modeled uncached input cost, read-only client capability reporting, the versioned stdio interface, paired bootstrap intervals, Claude/Codex hook responses, project-scoped MCP recovery, reversible managed project setup, private endpoint-scoped model snapshots and local scans, scoped memory audit/pagination, offline frozen-fixture attempt replay and protocol registration with modality-specific arms, trusted subprocess checks, scoped quality-suspension decisions, accessible local HTML filters, cache-aware policy, replayable filtered event export, report coverage/cost provenance, daily dashboard series with separate request/tool-output reductions, category decomposition, and offline model-route eligibility. A local subprocess test connects the Claude hook CLI to the recovery CLI. A second subprocess test covers the Julius-side Bulma stdio contract without Bulma adoption. A loopback HTTP server tests xAI request preservation and fail-closed response handling through the real urllib transport; this is a local protocol fixture, not a live xAI call or an agent benchmark.

`tests/fixtures` freezes event and optimization contracts from the initial TypeScript checkpoint `3616024`. Python and native Rust match its optimization receipts and the prior aggregate-report fields for the selected corpus; newer report evidence fields are additive. The historical TypeScript suite passed 51 tests before cutover; this is reference evidence, not an active second implementation.

The current suite additionally checks that session-delta usage never inflates request coverage, even with a request ID; that explicit artifact export defaults to metadata, requires raw-content opt-in, preserves project and expiration boundaries, and rejects unsafe destination paths; and that a benchmark adherence audit rejects missing, excess, misordered, or metadata-inconsistent attempt records. These are local contract checks. They do not supply independently observed task outcomes or a quality comparison.

Installer tests now inject interrupted update and removal transactions and verify recovery or refusal when a required backup is missing. The HTML task table has code-level checks for local filters and visible-row CSV export; one generated local report was opened and rendered in Chrome, but filter and download behavior have not received a full browser acceptance test. `doctor` produced an exact-version capability manifest for the detected Claude Code and Codex versions and passed Julius's local hook/MCP probe; it did not invoke either client. The archive smoke script resolves its macOS temporary prefix before strict symlink checks because `/var` is a symlink to `/private/var` on that host.

## Platform evidence

Local environment: macOS arm64, Python 3.12.10, Rust 1.98.1, PyO3 0.29.2, SQLite WAL/FTS5. Maturin produces a Python 3.11+ stable ABI macOS arm64 wheel. Its isolated installation was tested with Python 3.12. ABI compatibility metadata does not certify every supported interpreter or operating system.

The [public GitHub Actions run](https://github.com/ruverd/julius/actions/runs/35631751366) passed for commit `2a22c94` on hosted macOS ARM64 and Linux X64 runners: source tests, standalone build, archive smoke, and unsigned artifact upload succeeded in both jobs. The [Linux arm64 container script](../scripts/linux_container_smoke.sh) also passed on Debian Bookworm/glibc 2.36 with Python 3.11.2 and Rust 1.98, built a wheel and standalone archive, then completed temporary install/remove. These runs do not certify every native Linux distribution, WSL, or Windows. Both local standalone archives and CI artifacts are unsigned development builds. The managed archive installer has fixture-tested update/rollback and temporary install/remove smoke; clean-machine signed installers and trusted updates remain release work.

Local archive SHA-256 values for this source build: macOS arm64 `61aed63f668e5ac87601967da04cd8cac16cd00d669e73cb1f1003fc14079e21`; Linux arm64 `d4516740babe9b5b6d2f868f96f295422217cb96e1995366f2bf7b671246dd0d`. These hashes identify the locally built bytes; they are not publisher signatures. The hosted run linked above predates this source change; a new run is pending.

Local discovery found Claude Code 2.1.278 and codex-cli 0.154.0. The `doctor` local protocol probe passed hook candidate, MCP initialize, tool listing, and exact artifact restore in Julius subprocesses. Separate [live Claude fixtures](live-claude-validation.md) confirmed Claude called recovery, consumed a Bash hook candidate and restored its matching original, and produced one task-attributed session usage event through bounded print mode. One further bounded baseline/safe Claude pair completed in both arms; the safe arm's client-estimated session cost was USD 0.00358145 higher. A [live Codex usage probe](codex-live-probe.md) confirmed one synthetic `turn.completed.usage` JSONL record; two [temporary hook acceptance turns](codex-hook-probe.md) and one [actual Julius command turn](codex-hooks.md) confirmed `UserPromptSubmit` execution and model-visible additive context. These verify narrow capabilities on exact versions; they do not provide sent-request savings, task-quality evidence, or universal client coverage. Ollama at `127.0.0.1:11434` and LM Studio at `127.0.0.1:1234` did not respond.

A prior read-only `claude --mcp-config <temporary-file> mcp get julius-recovery` probe returned `not configured` (exit 1). The later live session superseded that inconclusive check: it connected to the temporary MCP server and called its recovery tool. Four bounded Claude model calls were made with synthetic input; one failed with a provider safeguard error and is retained in the [live evidence](live-claude-validation.md).

An exploratory [six-task bilingual Claude pilot](live-claude-pilot.md) made twelve further bounded synthetic sessions on Claude Code 2.1.278. Both arms passed five of six strict task checks, but on different tasks. The safe hook arm cost USD 0.01836680 more in client estimates and produced 404 more output tokens. One safe session stopped at the client's budget limit; one baseline session requested a denied command before completing. Corpus, order, and task hashes were recorded in the report; the later runner revision additionally writes registration before execution and partial results after each attempt. The observed run predates that persistence revision, so its in-memory reconstruction was checked offline rather than presented as pre-registered execution. Cache state was uncontrolled. It supplies no direct sent-request reduction or causal quality claim.

A separate [frozen tiny-repository pilot](live-repo-task-pilot.md) ran one English bug-localization task and one Portuguese code-comprehension task, each in baseline and safe-hook sessions. Both arms passed both exact-answer and tool-evidence checks. The safe arm cost USD 0.00056665 more in client estimates. Source files were too small and nonrepetitive to exercise compression; cache was uncontrolled. This remains exploratory workflow evidence, not a representative coding benchmark.

No live xAI request was made during this validation. The [loopback transport test](xai-loopback.md) confirms one HTTP POST, authorization/body preservation, usage parsing, bounded responses, and no automatic repeat on selected failures. A single live TypeSafe Choice gateway request with synthetic state succeeded: it returned `compress`, confidence `0.77`, 373 input tokens, 31 output tokens, and actual model `jev-1.13.0`. No price was configured, so dollar cost remained unavailable. This verifies the gateway's current wire shape for that one account and request, not task quality, calibrated confidence, or active Jev decisions. Jev remains shadow-only in Julius. The xAI adapter has no measured input or output savings; its provider charge field is recognized from the documented response shape, but actual account billing has not been reconciled. Safe xAI dispatch remains experimental pending a live function-call, restoration, and quality test.

The new [Jev replay](jev-shadow-evaluation.md) is offline and has no six-case live captures. xAI request comparison now keeps JSON-body token counts diagnostic unless the caller explicitly attests a complete model-input counter pinned to the responding model. xAI's [billing FAQ](https://docs.x.ai/developers/faq/billing) says standalone tokenizer counts may differ from inference prompt usage because the endpoint adds processing tokens. The ordinary Julius CLI still reports direct xAI input-token savings as unavailable.

## Open quality gates

- Broader exact-version client coverage and real request attribution remain necessary beyond the narrow Claude and Codex probes.
- A live runtime test must verify installed/loaded state without inferring hardware fitness.
- A representative task benchmark must register frozen repository snapshots, criteria, model/runtime versions, cache state, and valid baseline configurations, then verify the execution matched that registration. The [offline registration module](evaluation-protocol.md) validates declared manifests and paired arm assignments; the tiny-repository pilot is narrower and does not meet this gate.
- End-to-end evaluation must include Portuguese/English repository tasks, failures, retries, overhead, latency, and confidence intervals. The offline analyzer, frozen-fixture runner, six-task synthetic pilot, and two-task tiny-repository sample cover parts of this work, but no representative corpus or causal product result exists yet.
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
