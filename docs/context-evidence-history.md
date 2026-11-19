# Historical PR replay

The [manifest](../scripts/experiments/context-evidence-history.mjs) pins six
merged pull requests from Julius and Bulma. Each question follows behavior
changed or discussed in its PR. The manifest freezes the query, initial
budget and source lines before replay. At startup the runner verifies each
oracle against the pinned commit. It compares the default and opt-in paths
through the same candidate build of the compact stdio MCP server.

```sh
npm run build
node scripts/experiments/context-evidence-benchmark.mjs --historical --bulma-repo=/path/to/bulma
node scripts/experiments/context-evidence-benchmark.mjs --historical --bulma-repo=/path/to/bulma --reverse
```

Run from a Julius worktree with the pinned objects in its Git history. The
Bulma path supplies Git objects. The runner uses `git archive` to populate
temporary working directories and creates an isolated home for each lane.
Git staging, working-tree edits and personal or branch-cache notes remain
outside the replay. The command reads both local Git object stores offline.

Both modes receive the same question and budget. If an expected fact is
missing and a handle is available, the scripted reader makes one bounded
700-token `context.read` from the beginning of that object. It can then
request the full contents of a relevant file if the question or an MCP reply
identified its path. This policy is identical in both modes. The oracle
identifies missing facts and relevant paths, giving the reader information an
autonomous agent would need to infer. Each modeled file read contributes a
request and a response to the traffic estimate. Pilot integrity checks verify
quoted lines against the tree and verify full handle digests separately from
the measured reader's traffic.

The gate requires all oracle facts after recovery, zero case-level
regressions in initial fact counts, at least two additional cases complete
in the first response and at least 10% lower aggregate estimated traffic.
The report also records per-case and worst-case traffic, calls, and cold
latency through recovery. Each run alternates execution order across cases.
The repeat reverses the order within pairs. A short question has at most 15
whitespace-delimited words. The mix measures the sample design.

## Outcome

The historical replay failed the promotion gate. The pilot recovered all
13 facts against 9 for the default. Both modes left all six cases incomplete
in the first response. Estimated total traffic rose 13.1%. Across the three
cases where both modes achieved full final coverage, traffic rose 2.0%.

| Merged PR | Question | Initial facts, default → pilot | Final facts, default → pilot | Estimated total tokens, default → pilot |
| --- | --- | ---: | ---: | ---: |
| [Julius #42](https://github.com/ruverd/julius/pull/42) | Output-size comparison | 0 → 0 | 0 → 1 of 1 | 1,990 → 2,925 |
| [Julius #44](https://github.com/ruverd/julius/pull/44) | TypeScript default in the decision and code | 0 → 1 | 1 → 3 of 3 | 2,565 → 5,008 |
| [Julius #40](https://github.com/ruverd/julius/pull/40) | Stale crux snippets and cache file identity | 0 → 0 | 1 → 2 of 2 | 22,361 → 23,908 |
| [Julius #28](https://github.com/ruverd/julius/pull/28) | Two exact lines of MCP recovery guidance and dispatch | 0 → 1 | 2 → 2 of 2 | 4,406 → 4,630 |
| [Bulma #91](https://github.com/ruverd/bulma/pull/91) | Fallback message for sensitive output | 0 → 1 | 2 → 2 of 2 | 2,988 → 3,221 |
| [Bulma #75](https://github.com/ruverd/bulma/pull/75) | Replay decision and acceptance checks | 0 → 1 | 3 → 3 of 3 | 5,206 → 5,007 |
| **Total** | | **0 → 4** | **9 → 13 of 13** | **39,516 → 44,699** |

- Calls after initialization and tool listing rose from 36 to 37. Recovery
  or modeled file reads accounted for 12 and 13 of those calls. Largest
  absolute traffic was 23,908 tokens on the stale-context question. Its
  local fallback included the full `src/ask/ask.ts`. Largest relative
  increase was 95.2% on the extractor question, where the pilot recovered
  three facts and the default recovered one.
- Median cold latency was 11.64 → 13.85 s through the initial response and
  11.90 → 14.02 s through recovery in the first run. These are medians over
  six cold checkouts per mode and include startup and index creation.
- The selected sample had two short questions (33%) and four longer ones
  (67%). The exact-copy case had a 256-token initial budget and required
  recovery in both modes. Production query frequencies are unknown.
- Every pilot handle recovered byte-verified material. The first response
  frequently cited the right source while leaving the exact required line
  for recovery. This experiment grades literal evidence at the pinned
  locations. It measures `cl100k_base` estimates on observed protocol
  frames and modeled file-read envelopes. Provider usage, production
  economics and agent outcomes remain unmeasured. Different recovery
  policies could change the traffic totals.

The runner writes its JSON report and exits with status 1 when the gate
fails. The first revision stayed in draft on the strength of these results.

## Directed recovery replay

The initial reader's whole-file fallback dominated both expensive traces.
On the stale-context question, `src/ask/ask.ts` cost 19,984 estimated tokens
by itself, and the pilot also read `src/graph/load.ts` for 1,396 tokens.
On the Rust question, the pilot's bounded handle read used 742 tokens, then
the fallback to `src/graph/rust.ts` added 2,521. Those costs include requests
and responses. Run an individual case with `--case=stale-context-code` or
`--case=native-backend-decision` to inspect the phase totals.

The [directed selectors](compact-mcp.md#experimental-repository-evidence)
recover several cited passages from the retained snapshot, or one exact
source range. The benchmark exercises them through stdio MCP:

```sh
npm run build
node scripts/experiments/context-evidence-benchmark.mjs --directed
node scripts/experiments/context-evidence-benchmark.mjs --historical --directed --bulma-repo=/path/to/bulma
node scripts/experiments/context-evidence-benchmark.mjs --holdout --bulma-repo=/path/to/bulma
```

For the directed comparisons, both lanes use the same initial budget, up to
two 700-token handle reads and up to three 700-token local excerpt reads.
Default handle reads use an identifier taken from the question or the start
of the object. Pilot handle reads use the question plus excluded ranges
already visible to the reader, or a `next` reference from the first response.
Both lanes use the same lexical local fallback on paths visible in the
question or reply. The oracle stops either lane once its facts are complete.
It supplies no paths, search terms or byte ranges for recovery. Extra
integrity checks remain outside the measured reader traffic.

The six original PRs are now diagnostic. The separate holdout pins five
unseen PRs in the same [manifest](../scripts/experiments/context-evidence-history.mjs).
It includes simple lookups, decision-plus-code, an exact multi-line passage,
and an intentionally incorrect source reference tested against a real handle.
The original promotion thresholds still apply. Legacy-reader numbers above
and directed-reader totals measure different recovery policies.

## Marginal recovery replay

Build the previous published pilot at `2903c86` separately and pass its
compiled CLI to the reader. The first two lanes use that binary with the
default and opted-in modes respectively. The third uses the current build
with evidence enabled. Every lane reads the same pinned tree with the same
budgets and protocol. The evidence lanes use the same exclusion and recovery
rules. The default uses its existing literal and byte selectors. The gate
retains the original coverage and traffic thresholds, requires preserving
each fact obtained by the previous pilot, and requires less total traffic
than the previous pilot.

```sh
npm run build
node scripts/experiments/context-evidence-benchmark.mjs --marginal-holdout --bulma-repo=/path/to/bulma --prior-cli=/path/to/prior/dist/bin/julius.js
```

The new holdout was pinned in `585757b` before the ranking change. The old
holdout (`--holdout`) and original PRs (`--historical --directed`) remain
diagnostic. Each row includes fact IDs, initial citations, exact returned
byte ranges and phase counts. Transport bytes include modeled local reads.
The retained-byte audit verifies cited excerpts and the content digest
outside the traffic and latency measurements.

The previous pilot's holdout generated 2,377 additional estimated recovery
tokens against default, about 75% of the total increase. In the index reuse
case, both pilots initially quoted `src/investigation/index.ts` line 95. The
previous pilot missed the complementary hash check on line 97 in both
follow-up calls. Restore coverage signals from the excluded lines in the
snapshot, give independent query clauses and evidence kinds room, and rank
remaining clipped passages per estimated serialized token. Adjacent code
gets a soft bonus for completing a guard or statement. Direct file and line
requests retain the exact byte-oriented path.

## Transport and focused scope replay

The negative marginal-ranking build remains reproducible at `791dcae`.
The grouped line representation was first tested on that build with the
same selected passages. The tested branch then restored the original
ranking from `2903c86`. It offers two independent options for clients.
`format: "lines"` packs the same selected evidence in a smaller envelope.
`evidenceScope: "auto"` can narrow a strongly anchored query to one source
or help complete an adjacent guard on composition queries. The default
protocol and byte-range selectors retain their behavior.

The four replay lanes are unmodified `main` at `6b22b95`, the evidence pilot
at `2903c86`, the same selection with line transport, and line transport
with focused scope. Build the two reference CLIs separately, then run:

```sh
npm run build
node scripts/experiments/context-evidence-benchmark.mjs --transport-holdout --format-lines --focus-evidence --transport-control --bulma-repo=/path/to/bulma --default-cli=/path/to/main/dist/bin/julius.js --prior-cli=/path/to/prior/dist/bin/julius.js
```

The five fresh PRs were pinned at `0dcf557` before this experiment.
`--same-delivery` asserts identical ranges, citations, delivered fact IDs,
audited bytes, call counts and fallback paths in the format-only comparison.
The transport profile counts complete JSON-RPC responses for the original
JSON envelope, shared JSON fields, and grouped literal rows. It also counts
the quote rows alone as a lower bound. The end-to-end replay includes
requests, discovery, recovery and fallback reads, using the same limits and
visible-source rules as the prior directed replay.

The cost objective requires total traffic below both controls with every
fact they delivered still covered. The earlier promotion gate also requires
all facts, at least 10% savings against default, and two additional cases
completed by the first response. Cold stdio latency includes graph startup.

The experiment follows the design principles in [RTK's feature
reference](https://github.com/rtk-ai/rtk/blob/develop/docs/usage/FEATURES.md),
[Context Mode's architecture](https://github.com/mksglu/context-mode/blob/main/docs/how-it-works.md),
and [Aider's budgeted repository map](https://aider.chat/docs/repomap.html).

The first transport holdout became diagnostic after it exposed two missed
assertions in a named source. Keep its original result for comparison. The
follow-up gives exact, still-unquoted identifiers in a uniquely named source
priority before shortlisting evidence. It retains ordinary note composition.
The final five PRs were pinned separately at `cf519fa`. Use
`--named-source-holdout` in place of `--transport-holdout` to reproduce that
independent comparison with the same reference binaries and reader policy.
The [recorded per-case totals and fact IDs](context-evidence-named-source-results.json)
drive the historical replay table in the README. The synthetic comparison
retains its own report, source revision, and traces.
