# Lexical field-map cache pilot

Repeated queries currently reconstruct field Maps from the same immutable cached sidecar. The prepared cache reuses the document lookup and creates each document's field maps lazily after validation and scope filtering. Loader identity replacement on rebuild invalidates the derived cache through WeakMap keys.

A local offline benchmark compares the compiled change with the reconstructed pre-cache path. It uses 170 tracked TypeScript sources, 2,187 graph nodes, 46 frozen queries and five option combinations. All 230 complete results match, including scores, source, coverage and internal metadata. Each scenario has five rotated timing repetitions; repetitions are not independent quality samples.

| Measure | Uncached | Cached |
| --- | ---: | ---: |
| Warm median | 15.002 ms | 10.890 ms |
| Warm p95 | 28.645 ms | 22.136 ms |
| Retained heap delta after queries and forced GC | 11.32 MiB | 16.23 MiB |

Warm median time fell 27.4%; retained heap increased 4.91 MiB in this corpus. This is a tradeoff for repeated queries in long-lived processes, not a token reduction. Eager inverted postings were excluded because the earlier probe penalized first-query latency. Fields remain lazy for narrow first queries.

Fresh-process query timings are retained in the JSON. Their medians varied across local trials, OS caches were not controlled, and no cold-start speedup is claimed. Warm timings exclude process startup, MCP framing and agent execution. No provider calls, measured billing or agent task-success claims.

Validation on the isolated main-based branch: npm run build; npm test (1,541 passed, one skipped, zero failures); benchmark full-result parity. The integration test exercises repeated calls, unmodified input sidecars, edits, deletion and loader identity replacement. Existing scope and sidecar fallback regression tests remain unchanged.

Reproduce from this branch without external services:

```sh
npm run build
node scripts/experiments/lexical-cache-benchmark.mjs /tmp/julius-lexical-cache.json
npm test
```

The benchmark reconstructs only the pre-cache map creation from compiled ask.js and checks the expected code shape. It does not compare an arbitrary old release. Source, query, harness and compiled module hashes plus all timings are in lexical-cache-benchmark.json. Performance evidence remains one-machine, one-corpus evidence.
