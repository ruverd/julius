# Julius versus pinned Trail: local executable comparison

Date: 2026-10-22. Status: offline evidence, no production optimization added.

## Decision

Advance **selective recovery** to a broader experiment with ambiguous or absent
query hints. Do not expand generic investigation composition, persistent memory
or aggressive truncation from these results. Complete-output tasks need a
different delivery policy before any smaller default budget is justified.

The actual Trail executable is now compared with the actual Julius executable.
This replaces the inherited-schema approximation for this experiment, but does
not establish provider token savings, invoice savings, coding success or adoption
inside Claude, Codex or Grok.

## Results

All counts below are offline `cl100k_base` tokens over actual JSON-RPC NDJSON
messages, counted once. They include initialization, tool listing, discovery,
operation arguments/results and every recovery call. Each table row sums three
new synthetic repositories: TypeScript, Python and Go. Lower is better.

| Task | Trail | Julius compact, 1,200 budget | Julius compact, 400 budget |
| --- | ---: | ---: | ---: |
| Tiny API lookup | 3,586 | 2,068 | 2,065 |
| Select one required fact from a large result | 26,301 | 7,433 | 5,070 |
| Recover every byte of the large result | 26,301 | 37,793 | 58,670 |
| API plus 24 direct callers | 5,062 | 4,111 | 4,105 |
| Total, same 12 tasks | **61,250** | **51,405** | **69,910** |

The 1,200-budget arm reduces total wire payload by **16.1%** on this task mix.
The 400-budget arm **increases it by 14.1%**. This is not an estimate of the
frequency of these tasks in real use.

- Selective recovery reduces payload by **71.7%** at budget 1,200 and **80.7%**
  at budget 400. Each task needs one recovery call; the hint is stated in the
  task, not inferred from a missing answer or tuned after seeing the preview.
- Complete recovery increases payload by **43.7%** and **123.1%**, respectively.
  It needs 35 versus 115 recovery calls across the three tasks. Reassembled
  output must match its captured SHA-256, not merely contain selected facts.
- The composition arm needs **9,526 tokens**, versus **5,062** for Trail's
  separate API/caller calls: **88.2% more**. All expected caller names survive.
  Its structured report carries more information; that extra information does
  not earn a benefit under this task's declared objective.
- Julius's full six-tool interface needs **62,051 tokens** on the same 12 tasks,
  versus Trail's 61,250. The ablation shows that the inherited engine and brand
  changes alone are not the source of these savings.

### Interface savings versus useful-work savings

Cold interface discovery contributes substantially. For the three tiny lookups,
excluding initialization and tool listing leaves 247 tokens for Trail versus 808
for compact Julius at budget 1,200. The smaller initial interface wins the cold
session comparison while operation/discovery traffic itself is larger.

For selective recovery, excluding that initial interface still leaves 22,962
tokens for Trail versus 6,173 for compact Julius at budget 1,200. This mechanism
survives the interface ablation. These are not warm-session measurements: selected
operation-schema discovery is still counted, and actual hosts may cache or defer
schemas differently.

## Experiment contract and quality

The frozen [manifest](../../scripts/experiments/local-comparison-tasks.json)
defines four task types in each of three generated repositories. Each repository
has one core function, 180 marker-bearing functions and 24 callers. These fixtures
are new relative to the earlier idea probes, but are small synthetic cases, not
independent real-world repositories or a statistically held-out coding benchmark.

There are **51 executions**: four arms on 12 tasks, plus composition on the three
impact tasks. Each arm starts a fresh process, repository and home. Every arm
gets the same source bytes. Arm order alternates; there is one run per cell, no
confidence interval, latency claim or provider cache assumption.

All 51 final runs pass their declared evidence checks; none triggers the network
guard. A successful tiny lookup contains the required API name. Selective tasks
must expose the exact independently declared marker value. Complete tasks must
contain all 180 marker values, and compact recovery must reproduce every captured
byte. Impact tasks must expose the core name and all 24 caller names. These checks
do not establish correctness of a code patch, equivalence of every output field,
or a model's ability to choose the right calls.

The first calibration run used a file-path caller query at depth one. That query
returned file importers, not the function callers requested by the task. All 12
separate-call impact runs failed the quality oracle. The corrected script queries
`hello` explicitly in every separate-call arm. The failed
[calibration report](local-comparison-calibration.json) and its traces remain
available; they are not pooled into the final comparison or used to claim a
composition advantage. No production code was changed to make the cases pass.

## Provenance and isolation

- Trail: `b1211efd3eef0efa121b93800e5dd8e547aead77`, built from its own lockfile.
  All **380 source files** are checked against Git blob identities before running.
  Its actual `dist/bin/trail.js` entrypoint starts the CLI and MCP server. The
  upstream package and historical cache names are retained only in this isolated
  baseline, not restored as Julius compatibility behavior.
- Julius product revision: `0763d88a5bfd98aaef7c93d71346d99d9204723e`, built from
  its own lockfile. Its actual `dist/bin/julius.js` runs the full and compact arms.
- Runtime: Node 22.14.0. Exact lockfile, harness, manifest and generated source
  hashes are recorded in the report. Different parser/dependency versions between
  products are part of this product comparison, not isolated causal effects.
- Setup downloads npm dependencies. Trial execution has no provider keys, uses
  isolated homes, `CI=1` and `DO_NOT_TRACK=1`, and seeds the upstream update cache
  to suppress its registry poll. Source is not patched. A shared experiment-only
  preload rejects Node network operations and non-Git subprocesses, recording
  attempts. This is a guard for these audited Node executables, not an OS sandbox
  for arbitrary malicious native code.
- Graphs are structurally built once before each MCP session; build output and
  indexing cost are excluded. This tests already-indexed evidence retrieval, not
  zero-configuration cold onboarding. No LLM/deep indexing is used.

## Limits and next experiment

Provider usage, cost and coding accuracy remain **null**. The harness supplies
scripted calls; it does not count model planning, mistaken tool selection,
conversation replay, hidden host framing or reasoning tokens. Tool-list JSON may
be rendered differently by actual hosts. Upstream's own token-saving claims,
embedded in output, are counted as text but are not used as measurements.

Do not promote the 400-token budget globally. Next, freeze an independent set
containing absent hints, ambiguous symbols, unindexed files, mutations and mixed
complete/selective requests. Compare complete output, fixed preview and a small
test-only selector, charging every failed lookup and recovery. Preserve the
counterexamples. Only a successful broader offline trial justifies spending on
model/host trials with an explicit budget.

Persistent reuse and receiver-aware handoffs were not newly tested here. Earlier
[idea probes](idea-probes.md) still show that a cache hit alone does not reduce
delivered tokens, and a receiver without a valid context base needs full evidence.

## Reproduction and artifacts

From this repository, use a new temporary upstream directory. Do not point the
archive command at a directory containing user files.

```sh
TRAIL_PROBE_DIR=$(mktemp -d)
git archive b1211efd3eef0efa121b93800e5dd8e547aead77 | tar -x -C "$TRAIL_PROBE_DIR"
(
  cd "$TRAIL_PROBE_DIR"
  npm ci --ignore-scripts --no-audit --no-fund
  npm rebuild tree-sitter tree-sitter-typescript tree-sitter-python tree-sitter-go tree-sitter-java tree-sitter-kotlin tree-sitter-php tree-sitter-swift @davisvaughan/tree-sitter-r esbuild
  npm run build
)
npm ci --no-audit --no-fund
npm run build
node --import tsx --test test/local-comparison.test.ts
node scripts/experiments/local-comparison.mjs "$TRAIL_PROBE_DIR" /tmp/julius-local-comparison.json
```

The upstream install skips root lifecycle scripts (including telemetry stamping
and postinstall), rebuilds the named native packages, then runs the ordinary
build. The runner performs no install and deletes only its own trial directory.
Source/dependency setup failures stop the experiment; per-arm execution failures
remain in its report with their partial traffic and failed quality status.

- [Final report](local-comparison.json)
- [Final exact wire traces, gzip JSON](local-comparison.traces.json.gz)
- [Calibration report](local-comparison-calibration.json)
- [Calibration exact wire traces, gzip JSON](local-comparison-calibration.traces.json.gz)
- [Runner](../../scripts/experiments/local-comparison.mjs)
- [Offline execution guard](../../scripts/experiments/offline-guard.cjs)

Validation: build passed; 1,474 tests passed, one skipped, zero failed. New harness
tests reject quality loss, unknown counts and negative savings, verify binary
reassembly across UTF-8 boundaries, and reject omitted middle facts.
