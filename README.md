# Julius

Local context optimization with evidence you can inspect.

Julius is an early standalone implementation of the September 21, 2026 product proposal. Python owns the product core; Rust performs deterministic text processing through PyO3. It creates recoverable optimization candidates, imports usage, and reports what is known without inventing financial savings. It does not execute a coding agent or replace an inference runtime.

An explicit, experimental xAI Responses command can send an authorized Grok request and record provider-reported input/output usage. A guarded safe mode prepares recoverable tool-output candidates and handles Julius-only restore calls. Optional Jev shadow decisions can be requested separately. xAI paths have fixture tests only; one live Jev Choice gateway call validated its observed wire shape. None proves measured savings or agent quality.

## Develop and run

Requirements: Python 3.11+, uv, and a Rust toolchain for building from source. Installed native wheels do not require Rust. Native validation currently covers macOS arm64 with Python 3.12; Linux CI is configured but not yet certified.

```sh
sh scripts/dev.sh setup
sh scripts/dev.sh test
sh scripts/dev.sh build
uv run --no-sync julius --version
uv run --no-sync julius setup
uv run --no-sync julius doctor
```

The helper uses a repository-local Rust toolchain if one exists under `.tools`; otherwise it uses your normal toolchain. It does not edit shell profiles. Dependencies are locked in `uv.lock` and `Cargo.lock`. Maturin builds wheels in `dist/wheels`. Wheels are unsigned development artifacts, not a published package or a signed standalone release.

For an existing local wheel, install into your chosen virtual environment:

```sh
uv pip install --python /path/to/venv/bin/python ./dist/wheels/<matching-wheel>.whl
```

Verify `julius --version` identifies `julius-local 0.2.0`. Storage defaults to `.julius` in the current directory. Set `JULIUS_HOME` or pass `--data-dir` to choose a local store. Plain `setup` initializes storage and probes client versions. Project-specific `setup --project-root` previews a Claude configuration change and requires a matching plan hash before applying it. No Docker, Redis, mandatory cloud service, daemon, or model is needed for reports.

`julius doctor` also runs an offline subprocess roundtrip through Julius's Claude hook and recovery MCP server. Its `localProtocolProbe` result tests Julius code only; client version discovery does not certify Claude Code accepted the hook, connected the tool, or shortened a model request.

## Offline example

```sh
JULIUS_HOME=/tmp/julius-demo uv run --no-sync python examples/demo.py
uv run --no-sync julius savings --data-dir /tmp/julius-demo \
  --since 2026-09-21T00:00:00Z --until 2026-09-22T00:00:00Z --explain
```

This example is synthetic. The 10,000 → 4,000 → 3,000 stages produce 7,000 marginal token reduction, explicitly labeled as estimates. It proves arithmetic, not agent quality or causal savings. Repeat import is idempotent.

## Optimize and restore

```sh
uv run --no-sync julius optimize ./tool-output.txt --project app --profile safe
uv run --no-sync julius restore '<artifact-id>' --project app
uv run --no-sync julius artifacts delete '<artifact-id>' --project app
uv run --no-sync julius artifacts purge --project app
```

`observe` is the default profile. `safe` replaces eligible repeated neutral lines only when shorter and recoverable. Protected instructions, failures, opaque data, expired policies, missing approval, and implicit recompression prevent application. Rust performs the eligible text operation; Python retains permissions and storage boundaries. A missing native extension returns an unchanged candidate with `native_unavailable`.

Receipts distinguish bytes from heuristic token estimates. Originals expire after 24 hours by default; the artifact API accepts TTLs up to 30 days. Expired originals cannot be restored. Project scope and content hashes are checked. Denied and observe requests do not retain originals.

Optimization never transmits a request. A harness must preserve approvals, provide an authorized recovery tool, and record a sent transformation separately. Keeping an original does not prove an agent will know when to retrieve it. The filter has no end-to-end quality benchmark yet.

## Import and report

```sh
uv run --no-sync julius import ./events.jsonl
uv run --no-sync julius import ./claude.jsonl --format claude --project app --source session-1
uv run --no-sync julius import ./codex.jsonl --format codex --project app --source session-2
uv run --no-sync julius savings --since 7d --by model
uv run --no-sync julius usage --since 7d --by category
uv run --no-sync julius savings --task DEV-123 --json
uv run --no-sync julius export --format csv --since 7d > usage.csv
uv run --no-sync julius dashboard --output ./julius-report.html
uv run --no-sync julius models list
uv run --no-sync julius models list --runtime lmstudio
uv run --no-sync julius models scan --runtime ollama
uv run --no-sync julius models record --state-file ./model-snapshot.json
uv run --no-sync julius models history --endpoint http://127.0.0.1:11434 --model '<model-id>'
uv run --no-sync julius prices record --state-file ./price-snapshot.json
uv run --no-sync julius prices lookup --endpoint https://api.example.test --provider example \
  --model '<model-id>' --currency USD --tier standard --cache-regime default \
  --at 2026-09-21T00:00:00Z
```

Transcript importers are experimental and fixture-tested, reading only explicitly supplied files. [Integration contracts](docs/integrations.md) describe supported record shapes. Codex cumulative deltas are not an exact call count. Executable detection does not establish live compatibility. Ollama and [LM Studio](docs/lmstudio.md) discovery are read-only, bypass environment proxies, reject redirects, and are restricted to loopback; they never download or load models. [Model snapshots](docs/model-registry.md) retain caller-supplied historical facts by endpoint; an explicit [local scan](docs/model-scan.md) records facts from a selected runtime. No listing or snapshot proves hardware fitness.

`7d` means a rolling window, with inclusive start and exclusive end. Local date inputs convert to UTC; the report names its timezone. Unknown values stay unavailable. Negative reductions remain signed. Provider usage does not establish the cost of a counterfactual trajectory. Financial savings remain unavailable in CLI reports until an explicit comparable baseline is integrated. Subscription refunds and proprietary limits are never inferred.

Aggregate exports omit prompts and raw payloads. Project/model/source labels may still be private. The [dashboard](docs/dashboard.md) is self-contained HTML with no listener or external resources; it supports system light/dark appearance, accessible tables, and local filters by the selected model or client grouping. Existing output files are not overwritten.

## SDK

```python
from julius.sdk import Julius

with Julius('./.julius') as julius:
    result = julius.optimize(
        {'projectId': 'app', 'category': 'tool_output', 'content': tool_output},
        {'mode': 'safe', 'version': '1.0.0', 'approved': True},
    )
    # Your harness chooses whether to send result['candidate'], with its own permissions.
    # Record validated usage with julius.record_usage(event).
    print(julius.report({'projectId': 'app', 'since': '7d'}))
```

Public Python functions use snake_case; versioned event and receipt dictionaries retain camelCase JSON fields. Strict Pydantic schemas reject invalid counters, booleans used as integers, unknown envelope fields, and invalid timestamps. SQLite WAL preserves event history, explicit duplicate aliases, corrections, and atomic shared budgets. Batch import is atomic. Budget participants must use one ledger and one immutable budget definition.

`julius serve --data-dir <path>` exposes the same four SDK operations over bounded, versioned JSON Lines on stdin/stdout for a future Bulma harness. It does not run a model or own the harness workflow. See [stdio contract](docs/bulma-stdio.md).

Optional modules provide [caller-supplied pricing](docs/pricing.md), [snapshot-scoped FTS5 memory](docs/memory.md), and a [cache-aware decision helper](docs/cache-policy.md). They do not automatically change agent requests or create financial baselines in CLI reports.

`julius prices record/history/lookup` manages [local dated price evidence](docs/price-store.md) without contacting a provider. Lookup requires the endpoint, provider, model, currency, tier, cache regime, and timestamp; overlapping snapshots remain ambiguous. Task explanations can resolve a stored USD price only when a usage event or explicit baseline links its exact snapshot ID and model identity.

The experimental [Claude Code hook](docs/claude-hooks.md) and [project-scoped MCP recovery tool](docs/mcp-recovery.md) are callable through the CLI. An [ephemeral Claude launcher](docs/claude-runner.md) configures them for one session. Rewriting remains disabled in its default observe profile; safe mode requires an explicit recovery verification attestation. Hook candidates enter the ledger as unsent heuristic transforms. A [live synthetic test](docs/live-claude-validation.md) confirmed Claude Code 2.1.278 consumed a Bash hook candidate and restored its matching original through MCP; it did not establish sent-request token savings or task quality. The [Codex hook adapter](docs/codex-hooks.md) provides trusted additive context only and has no live rewrite test. [Managed Claude project configuration](docs/integration-management.md) supports a reviewable opt-in preview, hash-gated apply, and exact backup restoration on removal.

```sh
uv run --no-sync julius setup --project-root ./project --project app
# Review both diffs, then use the printed hash:
uv run --no-sync julius setup --project-root ./project --project app --apply-plan '<planHash>'
uv run --no-sync julius integrations remove claude --project-root ./project
```

The project must already contain a `.claude` directory. Default project setup installs an observe-only hook; persistent safe mode requires `--profile safe --recovery-verified` after checking the recovery tool in that client session. The attestation is not automatic certification. Setup changes only that project. Configuration backups live outside the project when the default `.julius` data directory is inside it; `setup` prints their path. Removal refuses drifted configuration instead of overwriting edits made afterward.

```sh
uv run --no-sync julius run --agent claude --project app --profile observe
# Enable safe rewriting only after verifying this project's recovery tool in Claude:
uv run --no-sync julius run --agent claude --project app --task DEV-123 --profile safe --recovery-verified
# Explicit bounded prompt-only observation; prompt stays out of Julius storage:
uv run --no-sync julius run --agent claude --project app --task DEV-123 \
  --prompt-file ./prompt.txt --model haiku --max-budget-usd 0.05
```

The [bounded print runner](docs/claude-print-runner.md) stores one client-reported `session_delta` usage event. It normalizes Claude's non-cached input, cache creation, and cache read into one input total without adding nested details twice. A CLI-reported USD total is labeled a client estimate, not a provider invoice. A [live synthetic run](docs/live-claude-validation.md) confirmed this narrow observation path. It does not expose each underlying provider call or prove saved tokens.

`julius probe codex --project app --task DEV-123` makes one explicit, read-only synthetic Codex model call in a temporary directory and records its JSONL `session_delta` usage. The [live probe](docs/codex-live-probe.md) verified this narrow path on codex-cli 0.154.0. It cannot attribute an actual model, provider charge, or token savings.

## Explicit remote calls and task economics

```sh
XAI_API_KEY=<dedicated-key> uv run --no-sync julius run --agent grok \
  --request ./xai-request.json --project app --task DEV-123 --profile observe
XAI_API_KEY=<dedicated-key> uv run --no-sync julius run --agent grok \
  --request ./xai-tool-result.json --project app --task DEV-123 --profile safe
TYPESAFE_API_KEY=<dedicated-key> uv run --no-sync julius jev shadow \
  --state-file ./decision-state.json --project app --task DEV-123 --post-call-threshold-usd 0.01
```

The observe-mode xAI request file must contain an explicit Responses API `model` and `input`. It forwards caller-supplied fields once; review requested server-side tools for effects before sending. Safe mode is a narrower, opt-in path for array input containing eligible `function_call_output` text, with a declared Julius restore function and `store` not set to `false`. It may send bounded continuation calls only when the model requests restoration. Each attempted call is recorded once, including incomplete attempts. The [whole-request measurement](docs/request-measurement.md) reports signed serialized-byte change and leaves token change unavailable unless a matching model/tokenizer counter is supplied through the SDK. Tool-output estimates and full-request counts have different scopes and must not be summed. xAI documents `store=true` by default; `"store": false` disables stateful response storage, but is not a zero-retention guarantee. Actual response model, input, output, cache, and provider-billed cost are recorded when supplied. Missing counters or charges stay unknown. Julius does not compress generated output or intercept Grok in another client. See [xAI adapter](docs/xai.md).

An offline [xAI optimization helper](docs/xai-optimization.md) prepares recoverable tool-output candidates. The [restore loop](docs/xai-tool-loop.md) now serves only Julius originals and records each provider attempt. These flows have fixture tests; real account behavior and quality remain unverified.

Jev receives only allowlisted context metadata and proposes `keep`, `retrieve`, or `compress`. Shadow mode always applies `keep` to production content and records any auxiliary call. Its budget is a post-call threshold, not a guaranteed pre-call charge cap; use only with a separately authorized spending limit. One live synthetic Choice call returned usage and actual model, with dollar cost unavailable; Julius has not benchmarked Jev task decisions. See [Jev boundary](docs/jev.md).

The offline [`analyze_task` API](docs/economics.md) can calculate modeled task cost and net savings when a caller supplies complete call coverage, a comparable baseline, and dated price snapshots. CLI savings remains unavailable without that evidence. Observed output tokens are usage; a signed task-level output difference requires an explicit comparable output baseline and complete coverage. It is not proof that Julius shortened generated answers.

An [offline paired-task analyzer](docs/evaluation.md) accepts explicit baseline and candidate trials, keeps failed runs and retries in totals, and reports unknown measurements as unavailable. A [frozen-fixture replay](docs/evaluation-runner.md) accepts individual attempt records through `julius evaluate replay --state-file replay.json` and calculates signed differences and bootstrap confidence intervals. It executes no tasks and has no benchmark corpus yet. A [quality guard](docs/quality-guard.md) evaluates supplied scoped outcomes through `julius policy check --state-file guard.json`, persists them with `policy record`, and can block `optimize --guard-file guard.json` for an explicitly configured project/model/strategy/version. Outcome collection and enforcement in client integrations remain unverified.

## Delivery status

Implemented: Python CLI/SDK and JSONL/stdio transport, strict event schemas, SQLite ledger, shared budget reservations, Rust candidate processing, recoverable artifacts, provider normalization, experimental transcript importers, Ollama/LM Studio discovery and append-only model snapshots, reports/exports/HTML, optional pricing and lexical memory, experimental xAI single-send/restore-loop and Jev shadow gateways, offline task economics, fixture replay, and scoped quality checks, ephemeral Claude launcher, managed project configuration, local hook/MCP probe, native wheels, and tests.

Pending: broad Claude/Codex/xAI compatibility validation beyond one successful synthetic Claude hook/MCP case, confirmed sent-request interception, routing, exact tokenizers, automatic pricing/baselines, symbol retrieval, structured memory, automatic cache-aware policy, measured production quality-based suspension, isolated task benchmarks, full task-level dashboard, signed distributions/updates, active Jev decisions, and actual Bulma harness integration. This repository claims no universal traffic coverage, causal savings, or quality improvement.

The initial TypeScript implementation is preserved in Git commit `3616024`; frozen contract fixtures check migration parity. Python and Rust are the active core. See [original delivery plan](docs/plans/2026-09-21-julius.md), [approved migration](docs/plans/2026-09-21-stack-migration.md), [product completion plan](docs/plans/2026-09-21-product-completion.md), [event contract](docs/events.md), and [validation](docs/validation.md).
