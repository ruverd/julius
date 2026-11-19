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
