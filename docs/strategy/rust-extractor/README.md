# Rust extraction pilot

Measured on 2026-11-03. Keep production CLI, MCP, ranking and orchestration in TypeScript. A standalone experimental Rust extractor reduced complete indexing time by 2.05–2.87x across the three local corpora, with exact extraction, graph, lexical-index and query parity. It did not materially improve warm queries. These results support further work on the hybrid extractor; they do not justify rewriting the whole engine in Rust or enabling this prototype by default.

## What ran

`scripts/experiments/rust-extractor/` contains an opt-in Rust `cdylib` loaded through Node-API, an adapter and a reproducible benchmark driver. The driver builds an isolated snapshot of the current working source and patches only that copy's compiled extraction entry point. No production source, npm dependency, installed integration or release changed.

The baseline uses Julius's current Node Tree-sitter extraction. The candidate compiles the **same installed Tree-sitter 0.25.1 core and TypeScript/TSX 0.23.2 grammar C sources**, then walks the tree and computes definitions, scoped receiver bindings, import references and unresolved edges in Rust. It returns compact tuples with definition identities, kinds, byte offsets, rows, visibility and owner, plus ordinal-based edge intents. It does not return an AST or replay cached baseline extraction. Rust parsers are reused per thread; each parsed tree is freed after extraction.

The adapter materializes the existing `NodeV1` and `RawEdge` forms. Existing TypeScript helpers still compute signatures, hashes, normalized search bodies and module residuals. TypeScript still resolves graph edges, persists caches, writes markdown cards, ranks queries and serves CLI/MCP. TS, TSX and JavaScript are covered; other languages retain their existing extraction path. The candidate retains the existing Node grammar initialization in build-tier selection, including its cost. This experiment does not measure a minimal standalone Rust executable.

Builds use locally cached Cargo dependencies with `--offline`; no downloads, models or configured external services were needed. Benchmark workers and real CLI/MCP processes used an offline network/child-operation guard, whose logs were empty. The inherited test suites were separate validation runs, outside benchmark timing.

## Measurements

One Apple M4 Pro machine, Node v22.23.2, Rust 1.99.1, release mode. Four rounds alternate baseline/candidate order. Each indexing phase starts a fresh worker; only the on-disk extraction cache carries between full, unchanged, edit, addition and deletion. Full indexing forces extraction and includes markdown cards. Timed API operations exclude module import; separate process wall times include startup/import/native loading. A fresh process does not imply a cold OS file cache. CPU frequency, OS cache and unrelated host load were not controlled. These small, local samples provide no production p95 or confidence interval.

| Corpus | Indexed files | Nodes | Resolved edges | Full build TS → hybrid | Speedup | Full-build peak RSS TS → hybrid |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Julius source | 173 | 2,201 | 5,766 | 1,389.48 → 484.73 ms | 2.87x | 266.2 → 164.3 MiB |
| Installed Commander source subset | 8 | 206 | 378 | 125.27 → 61.03 ms | 2.05x | 86.0 → 76.3 MiB |
| Generated two-package repository | 1,003 | 13,010 | 25,007 | 2,430.56 → 1,031.82 ms | 2.36x | 409.0 → 269.8 MiB |

Counts include the incremental probe file. Julius contains the current `src/` tree; Commander contains the installed package's seven JavaScript files, not its entire upstream repository. The generated fixture includes inheritance, calls, aliased imports and typed receivers. It remains repetitive generated code, not a representative production monorepo.

Including worker startup/import/native loading, full-build wall medians were 1,591.23 → 596.30 ms on Julius (2.67x), 198.70 → 132.88 ms on Commander (1.50x), and 2,762.49 → 1,213.43 ms on the generated fixture (2.28x). These whole-process numbers also include post-operation verification and worker output, so they are not a separate CLI-build benchmark. Reported peak RSS was captured before verification serialization, separately for each process/phase.

The Julius candidate's full build spent a median 229.50 ms in the native call, including serialization into a JS string, and 29.91 ms decoding/materializing its compact results. Compact extraction output was approximately 718 KB. Hashing, source-body normalization and all remaining TypeScript build work stay in the end-to-end full-build numbers above.

### Incremental builds

Medians in milliseconds. These are explicit complete rebuild calls with reuse enabled, not no-change query freshness probes. Edit changes one existing source file; addition creates one importing source file; deletion removes it. Parse/reuse counts were checked against both arms. Phase-specific peak RSS rows are retained in `summary.json`; incremental RSS did not reproduce the full-build reduction.

| Corpus | Unchanged TS → hybrid | One-file edit | Addition | Deletion |
| --- | ---: | ---: | ---: | ---: |
| Julius | 227.85 → 232.37 | 234.62 → 221.16 | 234.23 → 219.93 | 231.60 → 222.86 |
| Commander | 60.44 → 73.55 | 76.34 → 71.18 | 77.44 → 76.21 | 74.84 → 66.59 |
| Generated | 687.69 → 673.06 | 680.77 → 711.52 | 657.73 → 693.28 | 698.92 → 674.56 |

The initial local advancement gate required exact parity, at least 20% lower full-build median, no incremental or warm-query regression above 10%, and no build-phase peak-RSS regression above 10%. **The initial aggregate gate failed**: Commander unchanged builds regressed 21.7%. The gate and failed result have not been changed or hidden.

A separately recorded follow-up repeated only that unresolved case, after the test suites had exited: 12 fresh workers per arm, rotated order, same source/runtime/native binary and unchanged graph/index hashes. Medians were **77.50 → 78.54 ms, 1.35% slower**. This does not reproduce the initial 21.7% regression and suggests the small-case latency difference is unstable. It does not convert the first gate into a pass or establish universal non-regression. Further hybrid work should confirm incremental costs on larger real repositories before adoption.

### Queries

Warm API medians use 200 observations per arm/corpus across five mixed development queries, after warmup. CLI medians use eight fresh processes per arm/corpus over two queries, with automatic refresh disabled. Real MCP uses two sessions per arm, with initialization and schema discovery; six warm query observations exclude each session's first request. MCP includes automatic freshness checks. These samples establish evidence equality, not agent behavior or reliable tail latency.

| Corpus | Warm `ask` TS → hybrid | Fresh CLI `ask` | Warm MCP |
| --- | ---: | ---: | ---: |
| Julius | 5.80 → 5.80 ms | 158.72 → 149.82 ms | 42.94 → 42.67 ms |
| Commander | 0.82 → 0.86 ms | 95.63 → 97.69 ms | 33.00 → 23.21 ms |
| Generated | 52.68 → 52.27 ms | 274.71 → 264.63 ms | 88.92 → 87.44 ms |

The extractor does not run for these already-indexed warm queries. Do not attribute small query differences or the small Commander MCP sample to Rust extraction. Warm API peak RSS was approximately unchanged: 206.6 → 205.4 MiB on Julius, 83.4 → 83.7 MiB on Commander, and 444.7 → 449.1 MiB on the generated fixture. The full-build RSS improvement is not a general daemon-memory claim.

## Equality and validation

- Exact deep equality passed **1,223 extraction cases**: 186 on Julius, 21 on Commander and 1,016 on the generated fixture. These counts include the same 14 explicit boundary fixtures repeated in each corpus. Fixtures cover Unicode/astral characters, CRLF, TSX, imports and shadowing, receiver annotations and constructor parameter properties, duplicate identities, nested definitions, malformed syntax, large files, clipped search bodies and module residuals. Equality includes all ordered nodes and raw edges, source bodies, signatures, owners, spans and hashes.
- All graph and lexical-index hashes matched for all five build phases in four rounds across three corpora: **60 corresponding phase pairs**. Parse/reuse counts matched; Rust counters confirmed every full-build source took the Rust path, no unchanged source was extracted, and exactly one edited source was extracted.
- Complete `AskResult` equality passed **304 paired checks** across 76 distinct corpus/query/option cases, repeated in four rounds. Options include default ranking, lexical-only, scoped, and full-source responses with ranking metadata. Timed warm-query hashes, actual CLI JSON and actual MCP text also matched.
- The existing full `npm test` suite passed on the isolated TypeScript baseline and on a separate validation copy whose **source and compiled extraction entry points both invoke Rust**: **1,585 passed, one skipped, zero failed per arm**. Both native and WASM test coverage remain in the inherited suite. No CI behavior changed.
- Three dedicated native-boundary tests passed: argument/language rejection and recovery, repeated TS/TSX parser reuse, and UTF-8 byte offsets after astral/accented text. The isolated ordinary `npm run build` passed.
- The initial baseline suite had one infrastructure failure because its source snapshot lacked Git metadata. Disposable Git repositories were initialized for the validation snapshots; the complete baseline rerun passed, and the native suite had Git metadata before the affected test ran. The first failure log is retained. Test-suite times are not performance measurements.
- An initial timing attempt was stopped before the valid run because its baseline worker loaded the native addon and phases shared cumulative RSS. The valid harness avoids both problems. Only the corrected run contributes to the tables.

The driver verified production source hashes, frozen compiled runtime hashes, native binary identity and empty offline-guard logs after measurement. `validation.json` records toolchain/package versions, C input hashes, test log hashes and limitations. Provider usage, cost and agent correctness remain null. Language migration itself establishes no token reduction.

The final branch-wide `julius check --json` exited 1 with 20 heuristic conflicts in pre-existing `docs/compact-mcp.md`, `docs/context-economy.md` and `docs/strategy/agent-ab-haiku-v2.json` changes. It warned that only the first 400 KB of diff was checked. These experiment additions are untracked and were excluded, so this is not a clean learning-check review of the prototype. Existing files were not changed to satisfy those findings.

## Decision and remaining work

Continue with an isolated hybrid extractor experiment. First-build time and peak RSS improved enough to justify that narrower engineering investment. Existing cache reuse already removes most extraction work on incremental paths; ranking remains in TypeScript and does not improve from this change. The measured benefit therefore favors extracting an expensive kernel rather than moving CLI/MCP or rewriting all engine logic.

This is a development prototype, not a production backend. Adoption still needs a typechecked integration contract, deliberate backend/cache-version selection, parser and failure/resource limits, broader held-out real-corpus validation, platform/architecture packaging and fallback behavior. The pilot directly declares the small C/Node-API ABI it uses; it does not establish production-hardening or cross-platform safety. Only macOS Apple Silicon was exercised; Windows is explicitly unsupported by this build script. The native binary and Cargo target directory are ignored and are not shipped in the npm package. Existing MIT provenance remains applicable; dependencies are linked from their installed sources rather than vendored here.

## Artifacts and reproduction

- `plan.json`: premeasurement scope, gates and source/runtime/native identities.
- `report.json.gz`: lossless compressed raw timing, resource, counter and equality rows. Its decompressed SHA-256 is used by `summary.json` and `validation.json`.
- `summary.json`: medians, ratios and original gate results; `validation.json`: additional build/test/provenance evidence.
- `unchanged-confirmation-plan.json` and `unchanged-confirmation.json`: separately planned targeted repetition; initial result remains unchanged.
- `baseline-suite-initial.tap.gz`, `baseline-suite-confirmed.tap.gz`, `native-suite.tap.gz`: complete test logs, including the initial infrastructure failure.

With npm dependencies, Rust toolchain and locked Cargo dependencies already available locally:

```sh
node scripts/experiments/rust-extractor/build.mjs
node --test scripts/experiments/rust-extractor/contract.test.mjs
node scripts/experiments/rust-extractor/pilot.mjs /tmp/julius-rust-new docs/strategy/rust-extractor-new
node scripts/experiments/rust-extractor/summarize.mjs docs/strategy/rust-extractor-new
node scripts/experiments/rust-extractor/confirm-unchanged.mjs docs/strategy/rust-extractor-new
```

Choose a fresh work directory. Run measurements sequentially without competing tests or model inference. The reproduction driver writes an ordinary `report.json`; the checked-in artifact is compressed without changing its JSON contents. Current measured snapshots are under `/tmp/julius-rust-extractor-20261103-run2`; reproducing a particular dirty working source requires matching the recorded source hash. No commit, push, install or release was performed.

The bridge uses the documented [Node-API string and function interfaces](https://nodejs.org/api/n-api.html); both arms use the [Tree-sitter C parsing API](https://tree-sitter.github.io/tree-sitter/using-parsers/). Those API choices are implementation context, not independent evidence of the speedups.
