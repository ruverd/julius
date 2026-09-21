# Julius product completion plan

Status: active. Existing Python/Rust repository is a foundation, not the delivered product described in the original specification. This plan tracks remaining capabilities and external validation gates. No fixture test can turn an integration into tested live support.

## Implemented in this increment

- A1: experimental xAI Responses single-send command and SDK method, fixture-tested request preservation, two documented usage shapes, response model/ID, cache/output counters, provider charge ticks, and incomplete receipt behavior. No live xAI request or automatic compression.
- A2: offline task economics API with explicit comparable baseline, price snapshots, overhead, retries, chained sent transforms, incomplete coverage, and signed net. CLI report still cannot claim task financial savings without baseline evidence.
- D1: explicit TypeSafe Choice gateway and Jev shadow command. It records decision plus auxiliary usage and never applies the suggested action. The configured cost threshold is post-call, so active use needs enforceable pre-call budget control.
- E: versioned JSONL/stdio transport for the four requested SDK operations. Bulma adoption and shared process ownership remain untested.
- A/B: read-only doctor feature statuses for two exact locally observed client versions, with live capture and rewriting still unsupported.
- Validation: offline paired-trial analyzer with failed-run and retry denominators and bootstrap confidence intervals. A trusted-check runner now executes frozen local fixture tasks in isolated temporary directories. No representative corpus, non-inferiority test, or causal product result yet.
- Verification: local Python/Rust tests, Ruff, mypy, wheel build, and isolated wheel smoke pass on macOS arm64. Exact count is recorded in [validation](../validation.md). Bounded synthetic live Claude Code, Codex, and Jev probes ran; no agent quality benchmark or causal savings experiment ran.
- Follow-up: offline Claude `PostToolUse` replacement helper and CLI entry point, project-scoped MCP artifact recovery over stdio, additive-only Codex hook helper, reversible managed-config primitives, and cache-aware decision helper. The Claude hook and MCP server pass a local subprocess round trip; client acceptance and sent-request coverage remain unverified.
- Evaluation follow-up: paired bootstrap confidence intervals for measured trial differences. No causal product result is claimed from these fixtures.
- Current follow-up: ephemeral Claude Code launcher with observe default and a guarded safe hook, read-only LM Studio discovery, offline xAI recoverable tool-output candidates, and task-level output difference only for explicit comparable baselines with complete coverage. None establishes live client compatibility or automatic xAI input savings.
- Latest follow-up: local `doctor` hook/MCP subprocess probe, candidate-only Claude hook receipts, and a bounded xAI restore loop with per-attempt ledger accounting. Explicit xAI safe mode can send recoverable tool-output candidates; it reports heuristic candidate counts and no direct whole-request savings. Live acceptance, task quality, and economic benefit remain unverified.
- This increment: hash-gated preview/apply and reversible Claude project configuration, append-only endpoint-scoped model snapshots, and offline frozen-fixture replay with individual attempts. CLI acceptance tests and an isolated wheel smoke cover these paths. Fixture replay executes no task; model snapshots do not verify remote facts; project setup still lacks a live Claude session-level acceptance test.
- Follow-on increment: explicit loopback-only model scans persist observed local states; a scoped offline quality guard evaluates suspension thresholds; the HTML report shows unknown and negative values with accessible local group filters. These modules do not yet automate production policy, certify model hardware fitness, or provide the full task-level dashboard.
- Current increment: synthetic live Claude Code 2.1.278 sessions verified Julius MCP recovery and Bash `PostToolUse` replacement followed by restoration, plus client-reported session usage from bounded print mode. One earlier hook attempt failed with a provider safeguard error and remains in the evidence. A live Codex CLI 0.154.0 synthetic turn verified one JSONL session usage record. The xAI path now distinguishes serialized whole-request bytes, optional pinned tokenizer counts, and tool-output estimates; no live xAI request or causal savings proof exists. An opt-in persistent quality gate can block SDK/CLI optimization after scoped outcomes, but automatic outcome ingestion and quality benchmarks are still missing. Dated price evidence is available through explicit CLI record/history/lookup without default rates.
- A bounded live Claude baseline/safe synthetic pair completed in both arms, but safe cost USD 0.00358145 more in client estimates; direct input reduction remained unmeasured. Snapshot-scoped code-symbol indexing and optional MCP search, replayable raw event export, an offline trusted-check task runner, and cleaner report coverage/cost provenance are implemented and tested. See [live Claude evidence](../live-claude-validation.md). This is one descriptive pair, not a product benchmark.
- Latest increment: offline router returns fail-closed eligibility and tokenizer-matched cost recommendations without dispatching or reserving a shared budget. Dashboard aggregates daily input/output/cache/auxiliary series and mutually exclusive input categories. A local HTTP loopback test exercises the real xAI transport without a provider account. An optional Debian Bookworm Linux arm64 container built and smoke-tested a standalone archive; the current macOS archive and wheel were rebuilt and locally smoke-tested. These checks do not establish live xAI compatibility, causal savings, native Linux support, or a signed release.

## Scope decisions

- Grok was not named in the original proposal, but its provider belongs within the remote-model and authorized API-adapter requirements. Add xAI without making it a default model.
- The original proposal requires direct input reduction and accounting for actual output tokens. It does not promise shortening model-generated answers. Any future output-reduction feature needs its own quality evaluation and must not be silently folded into input savings.
- Jev is optional, starts in shadow mode, and cannot replace deterministic permission, budget, or fallback policy.
- CLI report and optimization calls must remain offline. An explicit execution command may send one authorized API request and record its observed usage.

## Work packages

### A1. Authorized xAI Responses API integration

Implement a pure request validator and a single-send adapter that uses the caller's dedicated xAI API key. Preserve system/developer/user roles, tools, approval decisions, and request shape. Attribute actual responding model and provider usage, including cached input and output. Return incomplete status when final usage is absent. Never assume requested alias equals actual model. Unit tests use local fixtures; live status remains experimental until a user-authorized request proves protocol behavior. Do not copy OAuth session credentials.

### A2. End-to-end savings accounting

Expose normalized input, output, cache, auxiliary calls, retries, local/remote location, and complete/incomplete state separately. Direct input reduction requires a sent transformation with a declared scope and tokenizer evidence. Financial savings require an identified comparable baseline, price snapshots effective at call time, and optimizer overhead exactly once. Unknown output baseline remains unknown. Verify negative savings and warm-cache losses.

### D1. Optional Jev shadow integration

Map only typed eligible choices (`keep`, `retrieve`, `compress`) to the Jev decision boundary confirmed by official documentation. Send minimal authorized state and record latency, cost, decision, and error. Shadow mode never changes the production candidate. Timeout, invalid action, exhausted budget, or missing service use deterministic fallback. Calibration and task quality tests precede active decisions.

### A/B. Native client integrations and install management

Claude and Codex adapters need explicit versioned capability manifests and non-destructive doctor probes of the actual hooks or logs used. Managed setup must show a config diff, back up prior settings, and restore them on removal. Verify two exact client versions in live local sessions; report observed/eligible/transformed denominators. Do not declare support from executable detection or JSONL fixtures.

### C. Context quality and recovery

Connect snapshot-scoped lexical/symbol retrieval to an authorized agent-facing recovery tool. Invalidate stale references by content hash. Add structured memory with origin, confidence, expiry, and project isolation. Cache-aware policy must count full requests and reject a compression candidate when cache economics are worse. Quality regressions trigger audited suspension after a minimum sample.

### D/E. Routing, Bulma, and evaluation

Route only at safe task boundaries among eligible models; consider hardware, context, tools, latency, budget, and price. Provide versioned JSONL/stdio interfaces so Bulma owns workflow and Julius owns ledger persistence. Evaluate against native clients, Headroom, RTK, and Context Mode only in compatible arms with frozen versions. Include task success, retries, output, cache, overhead, latency, Portuguese/English cases, failures, and confidence intervals. The 20% target remains a hypothesis.

### Release

Build and sign macOS/Linux distributions; validate installation, update, rollback, and uninstall on clean machines. WSL needs a separate test. A release lists exact architectures, runtimes, clients, and versions tested. Public claims derive from observed calls or controlled experiments with evidence labels and coverage denominators.

## Immediate acceptance checks

1. Grok request can be prepared offline; no API key is read until explicit execution.
2. A single authorized send records response ID, actual model, provider-reported input/output/cache, and incomplete usage honestly.
3. Input reduction and output usage appear separately; no output savings are claimed without a comparable baseline.
4. Jev shadow decisions never change sent content and fall back safely on timeout or cost cap.
5. No provider credentials or prompt content enter aggregate export.
6. Existing tests, wheel build, and isolated smoke remain green.
