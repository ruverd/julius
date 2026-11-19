# Repository evidence pilot

The opt-in compact MCP mode improved initial coverage from 4/12 to 11/12
required facts while preserving 12/12 final coverage. Estimated protocol
tokens fell 11.3% against the default mode in the same build and 10.1%
against unmodified `main`. The case requiring recovery of a long exact line
used 11.0% more estimated tokens than the same-build default.

The [historical replay](context-evidence-history.md) tested six merged PRs
from Julius and Bulma. It recovered more exact facts and used more traffic.
It failed the promotion gate.

## Method

Run `npm run build` followed by
`node scripts/experiments/context-evidence-benchmark.mjs`. The script starts
the real compact stdio MCP server in a fresh disposable checkout and home for
each query and mode. Each pair uses the same query, files, notes and initial
result budget. The baseline calls `julius_find_code` with its defaults. The
pilot adds `args.evidence: true`. The unmodified `main` control ran the same
fixtures with `--baseline-only` before implementation at `6b22b95`.

The fixture manifest fixes the expected facts, source paths and forbidden
text. The benchmark verifies every pilot quote against its stated file and
line, and checks the retained object digest through `context.read`. An
inherited note lead can omit its bullet marker and still count as a fact.
When a fact is absent, the scripted reader first follows an available MCP
handle. It may then simulate a host file read when a response identifies the
path. That read counts as a separate call with its own request and response.
Pilot integrity reads outside the scripted reader's delivery path are
excluded from the traffic and latency totals.

The gate required full final coverage with verified source evidence, zero
regressions in first-response coverage by case, at least two cases made
complete in the first response and at least 10% fewer estimated total
tokens against the matched default-mode control. Fixture assertions also
check note scope, supersession, inactive status, duplicate excerpts and a
case where the required exact line cannot fit in the initial budget.

## Results

| Case | Initial budget | Initial facts, default → pilot | Final facts, both | Estimated total tokens, default → pilot |
| --- | ---: | ---: | ---: | ---: |
| Parallel policy and shared test state | 300 | 1 → 3 | 3 | 1,503 → 1,157 |
| Retry policy and two code files | 350 | 1 → 3 | 3 | 1,457 → 1,139 |
| Active policy, duplicate and superseded notes | 300 | 1 → 2 | 2 | 1,303 → 1,079 |
| Code-only control | 300 | 0 → 1 | 1 | 1,187 → 1,029 |
| Note-only control | 300 | 1 → 1 | 1 | 1,166 → 1,043 |
| Exact signature requiring recovery | 256 | 0 → 1 | 2 | 1,903 → 2,113 |
| **Total** | | **4 → 11** | **12** | **8,519 → 7,560** |

- Initial response text fell from 1,276 to 460 estimated tokens. Total
  traffic includes initialization, tool listing, discovery, invocation,
  recovery and modeled local reads. Discovery accounted for 2,790 tokens in
  default mode and 2,972 in the pilot. Calls after initialization and listing
  fell from 26 to 20, with recovery and local-read calls falling from eight
  to one. The unmodified `main` control used 8,411 estimated total tokens.
- Median cold latency through the initial response was 998 → 1,751 ms in
  one paired run and 2,735 → 2,149 ms in a repeat. Through recovery the
  medians were 999 → 1,751 ms and 2,736 → 2,150 ms. Both runs include
  process startup and lazy graph builds and ran alongside local regression
  tests. Coverage and token totals reproduced. The direction of the latency
  difference changed between runs.
- The traffic numbers use `cl100k_base` on observed MCP JSON-RPC frames and
  modeled file-read envelopes. Provider tokens, billing, agent decisions
  and task completion were outside the experiment. The six synthetic cases
  inform an opt-in trial. Broader corpora, language coverage and live agent
  behavior still need evaluation.
