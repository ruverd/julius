# Optional hybrid Rust extraction

Julius can use an experimental Rust backend for TypeScript, TSX and JavaScript structural extraction. CLI, MCP, ranking, graph resolution, index persistence and incremental reuse stay in TypeScript. The default remains the existing TypeScript extractor; normal install/build/query commands do not compile Rust or fetch Cargo packages.

Build the optional addon from a source checkout, or from the installed npm package directory, with Rust, a C compiler and the npm Tree-sitter dependencies available:

```sh
npm run build:native
JULIUS_EXTRACTOR=rust julius build .
JULIUS_EXTRACTOR=rust julius mcp .
```

The build command uses locked, locally cached Cargo dependencies by default. To explicitly allow Cargo registry access for this build, run `npm run build:native -- --online`. macOS and Linux are supported build targets; Windows continues to use TypeScript. No prebuilt Rust binary is shipped, and no install hook builds one. Restart a long-running MCP process after building or replacing its addon.

`JULIUS_RUST_EXTRACTOR_PATH=/absolute/path/extractor.node` selects a trusted, explicitly configured addon instead of the package-local `native/extractor/extractor.node`. Set this in the process environment before starting Julius: the executable path is captured before CLI dotenv loading, so repository `.env` files cannot select native code. `JULIUS_EXTRACTOR=typescript` restores the default. Other languages keep their existing native/WASM path.

If the addon is missing, incompatible, throws unexpectedly, or returns an invalid packet, extraction falls back to the existing TypeScript implementation. Explicit `build` commands report an unavailable backend on stderr; build results also include `rustExtractor`, and the public `rustExtractorStatus()` API returns `disabled`, `ready` or `fallback` with its reason. Status describes addon availability, not a promise that every file uses Rust. Source over 4 MiB, ill-formed UTF-16, or trees exceeding 128 named-node depth/500,000 named nodes use TypeScript for that file. These bounds reduce native exposure; a native process crash cannot be recovered by JavaScript fallback.

The Node-API boundary requires protocol version 1 and validates tuple shapes, kinds, integer ranges, UTF-8 boundaries, node identity uniqueness and edge references before materializing graph data. Rust returns compact definitions and unresolved edges, not an AST. Both backends use the Tree-sitter core/grammar sources from the installed npm dependencies. Existing TypeScript helpers preserve signatures, normalized search bodies, residuals and hashes.

Extraction and freshness identities include the selected backend and loaded native binary's SHA-256. Switching backend or restarting with a different binary requires a fresh extraction. Unexpected runtime/protocol failure disables persistent reuse for that process, so a partially completed native run cannot certify a reusable snapshot. Intentional per-file input limits retain the backend identity and use the matching TypeScript fallback.

Validate the integration with:

```sh
npm run build
npm test
JULIUS_EXTRACTOR=rust JULIUS_TEST_RUST=1 npm test
```

On busy development machines, `npm test -- --test-concurrency=4` forwards the concurrency cap to Node's test runner. The Rust CI jobs use this cap to reduce contention in inherited wall-clock assertions; default suite behavior is unchanged.

CI preserves the existing TypeScript/native/WASM jobs and adds Linux/macOS jobs that compile the Rust addon and run the full suite with it enabled. `JULIUS_TEST_RUST=1` makes a missing build fail validation rather than silently skip native tests.

The earlier [local extraction pilot](strategy/rust-extractor/README.md) measured a 2.87x full-build improvement on Julius and lower full-build peak RSS, with matching results. Warm queries stayed unchanged; the initial incremental gate failed on one small corpus and a targeted repeat did not reproduce its magnitude. Those are local development observations from the archived pilot, not measurements of this hardened integration, held-out performance guarantees, provider savings or evidence for a full Rust rewrite. Broader real-repository validation and distribution work remain before making Rust the default.
