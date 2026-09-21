# Julius

Local context optimization with evidence you can inspect.

Julius is an early, standalone TypeScript/Bun implementation of the September 21, 2026 product proposal. It creates recoverable optimization candidates, imports usage, and reports what is known without inventing financial savings. It does not execute an agent, send model requests, or replace an inference runtime.

## Run locally

```sh
bun install --frozen-lockfile
bun test
bun run typecheck
bun run build
./dist/julius --version
./dist/julius setup
./dist/julius doctor
```

The compiled executable includes Bun. Development requires Bun; there is no Docker, Redis, or cloud dependency. The build is unsigned and is not a published package. Always verify `--version` identifies `julius-local` before using a binary found elsewhere on your PATH.

Storage defaults to `.julius` in the current directory. Set `JULIUS_HOME` or pass `--data-dir` to choose a shared local store. Setup initializes this store and probes client versions; it does not edit client settings or install hooks. Reports do not require a daemon or a model.

## Try an offline example

```sh
JULIUS_HOME=/tmp/julius-demo bun examples/demo.ts
./dist/julius savings --data-dir /tmp/julius-demo \
  --since 2026-09-21T00:00:00Z --until 2026-09-22T00:00:00Z --explain
```

The example is synthetic. Its 10,000 → 4,000 → 3,000 stages produce 7,000 marginal token reduction, labeled as estimates. It proves arithmetic, not agent quality, provider usage, or causal savings. Repeating the demo is idempotent.

## Optimize and restore

```sh
./dist/julius optimize ./tool-output.txt --project my-project --profile safe
./dist/julius restore '<artifact-id-from-output>' --project my-project
./dist/julius artifacts delete '<artifact-id>' --project my-project
./dist/julius artifacts purge --project my-project
```

`observe` is the default profile. `safe` currently replaces eligible repeated neutral lines only when the result is shorter and an original is available. Protected content, failures, instructions, opaque data, policy expiry, missing approval, and implicit recompression prevent application. Receipts distinguish bytes from heuristic token estimates. Originals expire after 24 hours by default; the SDK supports a shorter or longer TTL up to 30 days through `ArtifactStore`. `purgeExpired(projectId)` removes expired originals. Expiration is checked during restoration, even before cleanup.

Optimization returns a candidate and never transmits it. A harness must preserve its own approvals, use an authorized recovery tool, and explicitly record a sent transformation to attribute observed reduction. Keeping an original does not prove that an agent will know when to retrieve it. The first filter has no end-to-end quality benchmark yet.

## Import and report

```sh
./dist/julius import ./events.jsonl
./dist/julius import ./claude-transcript.jsonl --format claude --project app --source claude-session-1
./dist/julius import ./codex-rollout.jsonl --format codex --project app --source codex-session-1
./dist/julius savings --since 7d --by model
./dist/julius usage --since 7d --by category
./dist/julius savings --task DEV-123 --json
./dist/julius export --format csv --since 7d > usage.csv
./dist/julius dashboard --output ./julius-report.html
./dist/julius models list
```

Native transcript importers are experimental, fixture-tested, read-only adapters. They read only the path you explicitly supply. See [integration contracts](docs/integrations.md). Codex cumulative deltas are not treated as an exact number of calls. Detected Claude/Codex versions do not establish verified native compatibility. Ollama discovery is read-only and restricted to loopback; it never downloads or loads a model.

`7d` is a rolling window. Queries use an inclusive start and exclusive end. Date-only inputs use local midnight and are converted to UTC; reports include the local timezone. Financial values remain unavailable without a known model and explicit price provenance. Financial savings remain unavailable until a comparable baseline exists. Negative token reductions remain signed. Subscription refunds and proprietary limits are never inferred from token counts.

CSV/JSON exports contain aggregate data, not prompts or raw usage payloads. The dashboard is a self-contained local HTML export with no listener or external resources. Output files are created exclusively to avoid overwriting an existing report. Treat project/model/source labels as potentially private when sharing exports.

## SDK

```ts
import { Julius } from './src/sdk';

const julius = new Julius('./.julius');
try {
  const result = julius.optimize(
    { projectId: 'app', category: 'tool_output', content: toolOutput },
    { mode: 'safe', version: '1.0.0', approved: true },
  );
  // Your harness chooses whether to send result.candidate, with its own permissions.
  // Record validated usage with julius.recordUsage(event).
  console.log(julius.report({ projectId: 'app', since: '7d' }));
} finally {
  julius.close();
}
```

The typed SDK is a local source interface, not a published stability guarantee. The ledger validates events at runtime, deduplicates source IDs and explicit call identities, preserves corrections, and exposes atomic budget reservations. All participants must share the same ledger and budget identity to coordinate reservations.

## Implemented and pending

Implemented: immutable logical event history in SQLite WAL; explicit deduplication and reconciliation; atomic shared budget reservations; normalized provider usage; experimental transcript imports; scoped expiring artifacts; observe/safe candidates; offline reports, exports, HTML dashboard; runtime discovery; CLI and SDK; executable build. Optional SDK modules add [caller-supplied pricing](docs/pricing.md) and [snapshot-scoped FTS5 memory](docs/memory.md). These modules do not automatically alter agent requests or populate financial baselines in CLI reports.

Still pending: verified live Claude/Codex observation integration, native tool-output interception, actual request routing, exact model tokenizers, automatic pricing and financial baselines, symbol recovery and agent-facing retrieval integration, structured memory, cache-aware policy, strategy quality suspension, isolated task benchmark runner, interactive dashboard, managed client configuration/rollback, signed platform releases and updates, Jev, and Bulma harness integration. No benchmark, quality, or universal traffic coverage claim is made.

See the [implementation plan](docs/plans/2026-09-21-julius.md), [specification](docs/specification.md), [event contract](docs/events.md), and [validation record](docs/validation.md).
