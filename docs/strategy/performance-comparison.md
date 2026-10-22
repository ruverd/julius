# Delivery and index performance against pinned Trail

Date: 2026-10-22. Local evidence only; provider usage, cost and coding accuracy remain null.

## Integration scope

These artifacts describe the exact historical revisions recorded in their JSON, before integration with remote main at `3119fac`. The PR preserves remote main’s matching-line delivery and complete-fit behavior. Its new contribution is the benchmark tooling/evidence, shared snapshot enumeration, bounded offset scans and recovery/selection fixes. Historical percentages are not measurements of the rebased PR. Validation on the updated PR base: `npm run build` passed; `npm test` passed 1,517 tests, skipped one and failed zero.

## Decision

Keep selective/complete delivery and shared snapshot enumeration. Do not lower the default budget, expand generic composition, or claim end-to-end agent speedup. Direct invocation with known schemas remains a harness ablation rather than an additional advertised tool.

## Executable delivery trial

The [final report](performance-comparison.json) and [exact NDJSON traces](performance-comparison.traces.json.gz) contain 360 successful executions: ten synthetic evidence tasks, three languages, three repetitions and four arms. Arms rotate order. All executable source and dist trees are hashed before execution and checked again afterward. The candidate revision is recorded in the report; the subsequent index optimization is evaluated separately below.

Trail is pinned at `b1211efd3eef0efa121b93800e5dd8e547aead77`; its source files are verified against Git blobs. Prior Julius is `0376b7e`. All counts use offline `cl100k_base` over complete NDJSON traffic, including initialization, discovery, invocation and recovery. Each task starts a new process after an explicit build. The warm-session task adds two repeated calls within that process.

| Arm | Tokens across 90 executions | Tool calls excluding interface |
| --- | ---: | ---: |
| trail | 463,332 | 135 |
| compact-1200 | 396,258 | 552 |
| policy | 346,263 | 396 |
| policy-known-schema | 324,321 | 261 |

Policy spends **25.3% fewer tokens than Trail** and **12.6% fewer than prior Julius** in this specific mix. Calls fall from 552 to 396 against prior Julius, but remain above Trail's 135. These are fresh-session results, not a real-world task-frequency estimate or a direct comparison to the earlier 12-task percentage.

| Task | Trail | Prior Julius | Policy |
| --- | ---: | ---: | ---: |
| tiny | 10,758 | 6,204 | 6,303 |
| selective | 78,903 | 22,299 | 18,129 |
| complete | 78,903 | 113,379 | 75,495 |
| impact | 15,186 | 12,333 | 12,387 |
| absent-focus | 78,903 | 22,299 | 17,880 |
| ambiguous-focus | 78,903 | 22,299 | 18,099 |
| without-hint | 78,903 | 113,379 | 113,472 |
| after-edit | 15,447 | 12,603 | 12,657 |
| investigation-impact | 15,186 | 62,679 | 63,048 |
| warm-session | 12,240 | 8,784 | 8,793 |

Complete delivery requires `delivery: "complete"` with omitted budget. The no-hint case retains a loss against Trail when every byte is recovered. Tiny lookups and ordinary impact queries also cost slightly more than prior Julius because of added interface metadata. The investigation-impact task asks for the same caller identities as Trail's two direct operations; extra structured evidence and recovery remain substantially more expensive. That counterexample rejects unconditional composition.

Absent and ambiguous focus tasks have recovery hints declared before execution. Recovery is scripted, not inferred autonomously by a model. The ten tasks reuse one synthetic fixture family in TypeScript, Python and Go; they are not independent real-world coding tasks. Unsupported-file coverage, escaped literals, large matches, UTF-8 boundaries and stale-result invalidation are checked in automated tests.

## Timing

Retrieval timing sums request-to-response latency before harness response tokenization. Build and interface startup are separate fields. OS caches and background load are uncontrolled; three repetitions do not establish statistical significance. These timings exclude model reasoning and conversational replay.

- trail: median retrieval sum 31.8 ms; median build 369.6 ms.
- compact-1200: median retrieval sum 97.0 ms; median build 376.8 ms.
- policy: median retrieval sum 92.0 ms; median build 386.5 ms.

Policy reduces local retrieval latency slightly against prior Julius in this mix, but remains slower than Trail. Lower delivered traffic does not prove faster completion by an agent. Known-schema invocation removes discovery in the harness only; it does not prove host support, retained schemas or automatic tool adoption.

## Snapshot optimization

The [index profile](index-profile.json) exercises 101 TypeScript files and 1,001 functions: first investigation, ten repeated investigations, then a newly added caller. Both engines return identical evidence/coverage/unknowns hashes for every phase. Both invalidate reuse after the source addition.

Default snapshots previously enumerated the repository once for sources and again for configuration, both before and after execution. They now share the list when traversal policies agree: four Git enumerations become two. Configured includes, nested repositories and submodules retain separate walks when needed. Content hashing before and after execution remains mandatory.

- before: first 336.7 ms; warm median 46.5 ms; after edit 137.8 ms.
- candidate: first 292.8 ms; warm median 30.9 ms; after edit 87.6 ms.

This is one instrumented process per arm, with ten correlated warm observations, not a general speed claim. V8 samples include blocking native waits. The [targeted executable comparison](index-cli-comparison.json) and [traces](index-cli-comparison.traces.json.gz) rerun investigation-impact against Trail and prior Julius after this optimization: 36/36 executions passed. Median retrieval was 143.3 ms for policy versus 171.7 ms for prior Julius and 41.3 ms for Trail. Token totals stayed 63,048 versus 62,679 and 15,186 respectively. This improves local investigation time against prior Julius while preserving the composition counterexample.

## Calibration retained

An earlier 360-run [calibration report](performance-comparison-calibration.json) and [traces](performance-comparison-calibration.traces.json.gz) retain nine failures. The harness tried to parse plain Trail output as JSON in investigation-impact cells. A regression test now accepts plain output and only follows validated structured recovery envelopes. Those failures are harness defects, not Trail failures, and are not pooled into final totals.

## Reproduction

Use Node.js 20+ and built, isolated checkouts of the exact baseline revisions. Pinned Trail preparation follows [the previous comparison](local-comparison.md#reproduction-and-artifacts). Prior Julius must be a Git checkout at `0376b7e`, built from its lockfile.

```sh
npm run build
npm test
node scripts/experiments/performance-comparison.mjs /path/to/built-trail /path/to/built-before /tmp/performance.json
node scripts/experiments/performance-comparison.mjs /path/to/built-trail /path/to/built-before /tmp/index-cli.json investigation-impact
node scripts/experiments/index-profile.mjs /path/to/built-before "$PWD" /tmp/index-profile.json
```

Trials use isolated homes and the shared offline guard. No provider, telemetry collector or registry is contacted during execution. Dependency setup is separate. Guarded Node operations are not an OS sandbox for arbitrary native code.

## Final robustness fix and verification

After the two frozen executable trials, a regression test exposed an oversized literal that existed but could not fit alongside its delivery envelope. That response now uses `match: true` and `anchorOmitted: true`, with a recovery cursor, instead of claiming absence. This edge case is covered by exact-byte recovery tests; the recorded trial revisions remain the versions actually executed.

Final integrated validation: `npm run build` passed; `npm test` passed 1,501 tests, skipped one, failed zero (1,502 total). The two final executable trials passed 396/396 declared synthetic evidence checks. Existing `.gitignore`, `.ignore` and untracked planning files were preserved. No dependency, hosted service, default telemetry or model call was added.
