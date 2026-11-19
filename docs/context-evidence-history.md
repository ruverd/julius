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
fails. The implementation stays in draft on the strength of these results.
