# Julius product completion plan

Status: active. Existing Python/Rust repository is a foundation, not the delivered product described in the original specification. This plan tracks remaining capabilities and external validation gates. No fixture test can turn an integration into tested live support.

## Implemented in this increment

- A1: experimental xAI Responses single-send command and SDK method, fixture-tested request preservation, two documented usage shapes, response model/ID, cache/output counters, provider charge ticks, and incomplete receipt behavior. No live xAI request or automatic compression.
- A2: offline task economics API with explicit comparable baseline, price snapshots, overhead, retries, chained sent transforms, incomplete coverage, and signed net. CLI report still cannot claim task financial savings without baseline evidence.
- D1: explicit TypeSafe Choice gateway and Jev shadow command. It records decision plus auxiliary usage and never applies the suggested action. The configured cost threshold is post-call, so active use needs enforceable pre-call budget control.
- E: versioned JSONL/stdio transport for the four requested SDK operations. Bulma adoption and shared process ownership remain untested.
- A/B: read-only doctor feature statuses for two exact locally observed client versions, with live capture and rewriting still unsupported.
- Validation: offline paired-trial analyzer with failed-run and retry denominators and bootstrap confidence intervals. No task runner, frozen corpus, non-inferiority test, or empirical result yet.
- Verification: local Python/Rust tests, Ruff, mypy, wheel build, and isolated wheel smoke pass on macOS arm64. Exact count is recorded in [validation](../validation.md). No live provider or agent quality benchmark ran.
- Follow-up: offline Claude `PostToolUse` replacement helper and CLI entry point, project-scoped MCP artifact recovery over stdio, additive-only Codex hook helper, reversible managed-config primitives, and cache-aware decision helper. The Claude hook and MCP server pass a local subprocess round trip; client acceptance and sent-request coverage remain unverified.
- Evaluation follow-up: paired bootstrap confidence intervals for measured trial differences. No causal product result is claimed from these fixtures.

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
