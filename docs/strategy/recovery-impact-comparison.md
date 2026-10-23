# Recovery and impact delivery for 0.24.1

Date: 2026-10-22. Offline protocol counts, not provider usage or billing.

## Changes

`context.read` honors `delivery: "complete"` without a budget, returning the
requested byte range as one JSON header plus a verbatim body. Original handles,
digests and offsets remain valid. Explicit budgets still cap responses. Binary
and split UTF-8 ranges use base64. Contiguous prefix previews can be joined with
a recovered suffix. Matching-line previews can be trimmed or disjoint, so the
benchmark recovers their original bytes from offset zero before checking the digest.

Large change-impact reports first try a grouped index of every identity and
repeated edge provenance. Coverage, uncertainty, paths, spans, depth, relation
and confidence remain visible. Excerpts stay in the exact retained report under
its handle, with `detailsOmitted: true`. When the index cannot fit, partial-record
delivery reports truthful omissions. Complete delivery retains the detailed report.
Current main's behavior of returning complete small reports is preserved.

Compact MCP search uses a column heading, shorter singleton spans and one copy of
each metadata label. Every symbol retains its path, kind, span, incoming-edge
count and matched source. Ranking and truncation notices are retained. CLI
formatting is unchanged.

## Results

All 360 executions passed their declared evidence checks. No guarded external
operation was attempted. All nine no-hint policy executions recovered exact
captured bytes with one follow-up each. All nine composed-impact policy executions
returned every required caller identity without recovery.

| Task, nine executions | Pinned upstream | Historical policy | Current policy | Current recovery calls |
| --- | ---: | ---: | ---: | ---: |
| tiny | 10,758 | 6,303 | 6,429 | 0 |
| selective | 78,903 | 18,129 | 8,274 | 0 |
| complete | 78,903 | 75,495 | 63,789 | 0 |
| impact | 15,186 | 12,387 | 12,513 | 0 |
| absent-focus | 78,903 | 17,880 | 17,976 | 9 |
| ambiguous-focus | 78,903 | 18,099 | 13,098 | 0 |
| without-hint | 78,903 | 113,472 | 78,291 | 9 |
| after-edit | 15,447 | 12,657 | 12,783 | 0 |
| investigation-impact | 15,186 | 63,048 | 13,062 | 0 |
| warm-session | 12,240 | 8,793 | 8,919 | 0 |
| **All ten task types** | **463,332** | **346,263** | **235,134** | **18** |

Current policy uses 49.3% fewer protocol tokens than upstream in this mix,
and 32.1% fewer than the historical policy. Aggregate no-hint recovery is
0.8% below upstream; composed impact is 14.0% below. Small tasks can spend
more on the longer recovery instruction. These results do not establish savings
for arbitrary outputs, task frequencies or real agent sessions.

No-hint recovery by language, three executions each:

| Language | Pinned upstream | Current policy | Reduction |
| --- | ---: | ---: | ---: |
| typescript | 27,921 | 27,387 | 1.9% |
| python | 23,601 | 24,183 | -2.5% |
| go | 27,381 | 26,721 | 2.4% |

Python retains a regression despite the aggregate improvement. Matching-line
previews must be recovered from their original object, so their initial delivery
adds traffic before a complete read. This cost is included rather than hidden.

Validation: npm build passed; npm test passed 1,525 tests, skipped one, failed
zero. Native grammar compatibility and installation smoke checks passed for
`@ruverd/julius@0.24.1`. Regression tests cover explicit caps, binary and UTF-8
ranges, grouped identities and edges, nonstandard IDs, retained full-report bytes,
compact search locations, ordering and truncation notices.

## Method and limits

The [report](recovery-impact-comparison.json) and
[NDJSON traces](recovery-impact-comparison.traces.json.gz) use the same frozen
ten-task manifest and generated TypeScript, Python and Go fixtures as the
[historical comparison](performance-comparison.md). Each arm has nine executions
per task, with three repetitions and rotated arm order. Pinned upstream and
prior Julius checkouts remain unchanged. Source and compiled trees are hashed
before execution and verified afterward. The measured candidate is commit
`625693a046ebc011d2c29ec09e0a03385a1b2a46`, based on current main with its updated
literal selection and dependencies. The report records its source, dist and
lockfile hashes. Later documentation changes preserve those measured sources.

Sequential recovery explicitly requests complete delivery. The no-hint initial
request still has neither a hint nor complete-delivery intent. This follow-up
exercises the published instruction; it is a scripted policy enabled by the
runtime, not proof that a model will choose it autonomously. Hinted searches
retain bounded recovery.

All initialization, discovery, invocation and recovery messages are counted once
as complete JSON-RPC NDJSON using offline `cl100k_base`. Full recovery verifies
the captured object's digest. This checks exact Julius output recovery, not byte
equality with upstream's different formatting. Caller and marker oracles remain
unchanged. Provider usage, cost and coding accuracy stay null. Timing is
uncontrolled, including concurrent local test activity; no latency gain is claimed.
Historical reports and traces remain unchanged.

## Reproduction

Use built, isolated checkouts of pinned upstream
`b1211efd3eef0efa121b93800e5dd8e547aead77` and prior Julius `0376b7e`, prepared
as described in the [original comparison](local-comparison.md#reproduction-and-artifacts).
Check out the measured candidate commit, then run:

```sh
npm ci --engine-strict
npm test
node scripts/experiments/performance-comparison.mjs /path/to/built-trail /path/to/built-before /tmp/recovery-impact.json
```

Trials use isolated homes and the existing offline guard. No model, paid service,
telemetry collector or registry is contacted during trial execution. Dependency
installation is a separate explicit setup step.
