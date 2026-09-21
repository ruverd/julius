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

Verify `julius --version` identifies `julius-local 0.2.0`. Storage defaults to `.julius` in the current directory. Set `JULIUS_HOME` or pass `--data-dir` to choose a local store. Setup initializes storage and probes client versions; it does not change client configuration. No Docker, Redis, mandatory cloud service, daemon, or model is needed for reports.

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
```

Transcript importers are experimental and fixture-tested, reading only explicitly supplied files. [Integration contracts](docs/integrations.md) describe supported record shapes. Codex cumulative deltas are not an exact call count. Executable detection does not establish live compatibility. Ollama and [LM Studio](docs/lmstudio.md) discovery are read-only, bypass environment proxies, reject redirects, and are restricted to loopback; they never download or load models.

`7d` means a rolling window, with inclusive start and exclusive end. Local date inputs convert to UTC; the report names its timezone. Unknown values stay unavailable. Negative reductions remain signed. Provider usage does not establish the cost of a counterfactual trajectory. Financial savings remain unavailable in CLI reports until an explicit comparable baseline is integrated. Subscription refunds and proprietary limits are never inferred.

Aggregate exports omit prompts and raw payloads. Project/model/source labels may still be private. The dashboard is self-contained HTML with no listener or external resources; it supports system light/dark appearance and accessible tables. Existing output files are not overwritten.

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

The experimental [Claude Code hook](docs/claude-hooks.md) and [project-scoped MCP recovery tool](docs/mcp-recovery.md) are callable through the CLI. An [ephemeral Claude launcher](docs/claude-runner.md) configures them for one session. Rewriting remains disabled in its default observe profile; safe mode requires an explicit recovery verification attestation. Hook candidates enter the ledger as unsent heuristic transforms. The [Codex hook adapter](docs/codex-hooks.md) provides trusted additive context only. Local tests verify protocol shapes and recovery; neither client has passed a live rewrite test. [Managed configuration primitives](docs/managed-config.md) and a [Claude project-config planner](docs/claude-config.md) are not yet connected to setup/remove commands.

```sh
uv run --no-sync julius run --agent claude --project app --profile observe
# Enable safe rewriting only after verifying this project's recovery tool in Claude:
uv run --no-sync julius run --agent claude --project app --profile safe --recovery-verified
```

## Explicit remote calls and task economics

```sh
XAI_API_KEY=<dedicated-key> uv run --no-sync julius run --agent grok \
  --request ./xai-request.json --project app --task DEV-123 --profile observe
XAI_API_KEY=<dedicated-key> uv run --no-sync julius run --agent grok \
  --request ./xai-tool-result.json --project app --task DEV-123 --profile safe
TYPESAFE_API_KEY=<dedicated-key> uv run --no-sync julius jev shadow \
  --state-file ./decision-state.json --project app --task DEV-123 --post-call-threshold-usd 0.01
```

The observe-mode xAI request file must contain an explicit Responses API `model` and `input`. It forwards caller-supplied fields once; review requested server-side tools for effects before sending. Safe mode is a narrower, opt-in path for array input containing eligible `function_call_output` text, with a declared Julius restore function and `store` not set to `false`. It may send bounded continuation calls only when the model requests restoration. Each attempted call is recorded once, including incomplete attempts; tool-output candidate counts remain heuristic and do not prove whole-request savings. xAI documents `store=true` by default; `"store": false` disables stateful response storage, but is not a zero-retention guarantee. Actual response model, input, output, cache, and provider-billed cost are recorded when supplied. Missing counters or charges stay unknown. Julius does not compress generated output or intercept Grok in another client. See [xAI adapter](docs/xai.md).

An offline [xAI optimization helper](docs/xai-optimization.md) prepares recoverable tool-output candidates. The [restore loop](docs/xai-tool-loop.md) now serves only Julius originals and records each provider attempt. These flows have fixture tests; real account behavior and quality remain unverified.

Jev receives only allowlisted context metadata and proposes `keep`, `retrieve`, or `compress`. Shadow mode always applies `keep` to production content and records any auxiliary call. Its budget is a post-call threshold, not a guaranteed pre-call charge cap; use only with a separately authorized spending limit. One live synthetic Choice call returned usage and actual model, with dollar cost unavailable; Julius has not benchmarked Jev task decisions. See [Jev boundary](docs/jev.md).

The offline [`analyze_task` API](docs/economics.md) can calculate modeled task cost and net savings when a caller supplies complete call coverage, a comparable baseline, and dated price snapshots. CLI savings remains unavailable without that evidence. Observed output tokens are usage; a signed task-level output difference requires an explicit comparable output baseline and complete coverage. It is not proof that Julius shortened generated answers.

An [offline paired-task analyzer](docs/evaluation.md) accepts explicit baseline and candidate trials, keeps failed runs and retries in totals, and reports unknown measurements as unavailable. It calculates bootstrap confidence intervals when enough paired trials exist. It has no built-in task runner or benchmark corpus yet.

## Delivery status

Implemented: Python CLI/SDK and JSONL/stdio transport, strict event schemas, SQLite ledger, shared budget reservations, Rust candidate processing, recoverable artifacts, provider normalization, experimental transcript importers, Ollama/LM Studio discovery, reports/exports/HTML, optional pricing and lexical memory, experimental xAI single-send/restore-loop and Jev shadow gateways, offline task economics, ephemeral Claude launcher, local hook/MCP probe, native wheels, and tests.

Pending: verified live Claude/Codex/xAI/Jev integrations, confirmed sent-request interception, routing, exact tokenizers, automatic pricing/baselines, symbol retrieval, client-verified recovery registration, structured memory, automatic cache-aware policy, quality-based suspension, isolated task benchmarks, interactive dashboard, managed setup/remove, signed distributions/updates, active Jev decisions, and actual Bulma harness integration. This repository claims no universal traffic coverage, causal savings, or quality improvement.

The initial TypeScript implementation is preserved in Git commit `3616024`; frozen contract fixtures check migration parity. Python and Rust are the active core. See [original delivery plan](docs/plans/2026-09-21-julius.md), [approved migration](docs/plans/2026-09-21-stack-migration.md), [product completion plan](docs/plans/2026-09-21-product-completion.md), [event contract](docs/events.md), and [validation](docs/validation.md).
