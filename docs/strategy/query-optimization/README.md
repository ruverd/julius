# Query speed, context size and evidence validity

Local production changes on 2026-10-30. Keep the existing TypeScript stack and retrieval ranking. Optimize the measured PageRank hot path, omit redundant rendered descriptions, and stop returning stale learned code as current evidence. Measurements were local; no release or installation was performed.

## Changes

- PageRank uses numeric ordinals and reusable double buffers for topologies with at least 256 nodes. Active-node encounter order, duplicate-edge order and floating-point addition order match the previous Map implementation exactly. Smaller topologies retain the sparse Map walk. The first dense-only prototype regressed Commander and was revised; its observations remain under `dense-prototype/`.
- `formatAsk` omits a hit's description only when that complete string already occurs verbatim in that same hit's code. Raw `AskResult` fields, code excerpts, paths, relations, notes, distinct descriptions and recovery contents remain available. No code pruning or smaller default budget was introduced.
- Lexical and structural query hits and file API results no longer present a summary marked `stale` as current. Source rendering ignores a stale crux and reads the current indexed source span instead. A real incremental-build regression test changes a learned function from returning 7 to returning 9 and verifies that lexical and caller queries return 9, without the old summary.
- Graph and lexical-index caches now compare inode, device and ctime as well as size and mtime. Reads verify identity again after parsing and retry once on replacement. Continued churn returns null instead of caching a mismatched snapshot. This addresses actual stale-cache reuse after an atomic replacement that preserves size and mtime. Explicit rebuild invalidation remains in place. This is a stronger file-identity check, not a claim that filesystem metadata proves content identity against every concurrent or adversarial writer.

## Measured query execution

Both arms are isolated actual builds, including the pre-existing lazy lexical maps. Five corpus copies and queries are identical between arms. Four rounds alternate arm order; each arm/corpus has 100 warm API observations across five queries and 12 fresh CLI processes across three queries. A fresh process does not imply a cold OS cache. These are local diagnostics on one machine, not independent task samples or production service guarantees.

Warm in-process `ask` medians in milliseconds:

| Corpus | Before | After | Median time change |
| --- | ---: | ---: | ---: |
| Julius | 14.24 | 9.62 | -32.4% |
| Click | 3.09 | 3.18 | +2.7% |
| Commander | 1.62 | 1.50 | -7.4% |
| Zod | 2.95 | 2.14 | -27.3% |
| Generated 13,004-node repository | 90.48 | 55.54 | -38.6% |

Julius warm API p95 decreased from 44.84 to 27.26 ms; the larger fixture from 123.90 to 82.34 ms. These are empirical percentiles of a small, mixed-query sample. Large-fixture peak warm-worker RSS median decreased from 378.8 to 335.6 MiB; retained heap was approximately unchanged. Some smaller corpora used more peak memory. Do not generalize a memory improvement to every workload.

Cold CLI timings were much noisier than the first pilot: Julius medians were 905.54 and 477.82 ms, while Click regressed from 171.06 to 192.96 ms and Zod from 135.48 to 141.19 ms. These are recorded limitations, not omitted results. The change is not uniformly faster, and the cold CLI figures do not establish a stable startup improvement.

The development gate required exact result parity, preservation of every code excerpt and pointer, a positive aggregate protocol-token reduction, at least 20% lower large-fixture warm API median and no real-corpus warm API regression above 5%. The final candidate passes those local gates. The 256-node dispatch was chosen after observing this development pilot, so this is tuning and regression validation, not held-out performance evidence.

## Tokens and actual MCP

The first real MCP comparison counted every NDJSON request and response, including initialization, tool listing, schema discovery, default previews and complete suffix recovery. Total local `cl100k_base` protocol counts decreased from 100,085 to 97,442 tokens, 2.64%. This measures those exchanges, not provider usage, billing or host prompt replay.

A second measurement used three alternating session pairs per corpus. Client tokenization was deferred until after each child exited, outside latency timing, and full request/response traces were retained. Counts decreased from 300,240 to 292,311 tokens, also 2.64%. Recovery verified total bytes and SHA-256 of each reconstructed response. The first batch's recovery-call counts were unchanged, so this gain does not depend on skipping requested evidence.

End-to-end latency remains unsettled. In the second batch, warm request-chain medians were 49.81 to 61.47 ms on Julius, 48.35 to 44.89 on Click, 89.66 to 43.28 on Commander, 49.69 to 56.93 on Zod, and 134.14 to 112.77 on the larger fixture. Several directions changed from the first batch. That path includes freshness checks, source reads, retention/accounting writes, encoding and process scheduling; the isolated ranking improvement does not establish an overall MCP speedup. OS cache, concurrent machine load and filesystem latency were not controlled. The measurements justify keeping the numerical hot-path improvement; they do not close investigation of protocol latency.

No model or autonomous agent was run. Provider usage, provider cost and coding-task success remain null. Local protocol counts do not establish token savings inside an actual agent conversation.

## Correctness and checks

Exact serialized `AskResult` parity passed 432 scenarios across Julius, Click, Commander, Zod and the generated fixture. It includes scores, order, coverage, file selection metadata, source excerpts and pointers. Scenarios include scoped, lexical-only, structural, full-source and unmatched queries. Formatting checks verify that every original code excerpt, pointer and description still occurs in rendered output.

The numerical test compares the new implementation with a frozen pre-change reference over 300 deterministic graph/option combinations, including both sides of the dispatch threshold, duplicate/unresolved edges, filtered nodes, seed order, dangling nodes and different iteration/restart options. Exact entry order and floating-point values are checked. Existing graph-rank integration tests remain active.

Three additional regressions test redundant rendering, stale learned evidence and metadata-preserving cache replacement. Those three fail against the old build and pass against the new one. They verify changed behavior rather than merely reimplementing the new code.

`npm run build` passed. The default full `npm test` run had 1,577 passes, one skip and one failure: the pre-existing upkeep-hook test took 2,075 ms and exceeded its 2,000 ms wall-clock assertion, labelled `no network round trip`. All seven tests in that file passed on isolated rerun. That test uses elapsed time as a network proxy; the result does not itself establish a network request. Measurement workers and real CLI/MCP processes used network/external-command guards, whose logs remained empty. The subsequent full run used the same runner and isolated home with Node test concurrency limited to four: 1,578 passed, one skipped, zero failed. Counts and log hashes are recorded in `validation.json`; compressed TAP logs retain both the initial failure and the clean full rerun.

The generated fixture has two scopes and containment/import edges, not a rich call graph. Real external corpora are the same pinned source subsets used by the earlier retrieval experiments. Queries were reused for development; no retrieval-quality or agent-adoption improvement is claimed.

## Artifacts and reproduction

- `plan.json`, `report.json.gz` and `summary.json`: final before/after builds, identities, timings, exact result hashes, formatting counts and gate outcomes.
- `dense-prototype/`: the unsuccessful first dense-only variant, retained separately.
- `protocol-confirmation.json` and `protocol-traces.json.gz`: alternating session measurements and actual NDJSON traffic, counted after timing.
- `change.patch.gz`: only this task's production changes, relative to its initial working tree. Pre-existing cache changes and other workers' files are preserved.
- `test/fixtures/pagerank-reference.mjs`: the frozen numerical oracle.

The original before build is `/tmp/julius-optimization-20261030/baseline`; the final after build is `/tmp/julius-optimization-final-20261030/candidate`. Frozen corpora and query inputs are under `/tmp/julius-selective-20261030`. To repeat, use a fresh work directory containing a built `baseline/`; decompress and reverse `change.patch.gz` in a disposable copy of the final source to reconstruct those three before files. Build both with the same installed npm dependencies. The driver copies the current built product into a fresh `candidate/` and refuses to overwrite one.

```sh
npm run build
node scripts/experiments/query-optimization.mjs <fresh-work-with-baseline> /tmp/julius-selective-20261030 <fresh-report-directory>
node scripts/experiments/query-optimization-summary.mjs <fresh-report-directory>
node scripts/experiments/query-protocol-confirm.mjs <same-work> /tmp/julius-selective-20261030 <same-report-directory>
npm test
```

Run benchmarks sequentially without a concurrent test suite. The archived reports are gzip-compressed without changing their JSON contents; reproduction writes plain `report.json`. Those reports bind source/runtime/harness hashes. The measured production files were also compared directly with the final working-tree versions.
