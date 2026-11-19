# Compact MCP

The default server advertises only `julius_discover` and `julius_call`, even in a
fresh repository. Discovery lists short operation descriptions; provide
`operation` to fetch just that operation's schema. The allowlist includes
`investigation.execute`, six graph operations, and
`context.capture`, `context.read`, and `context.stats`.
There is no shell or arbitrary code execution operation. Graph calls build the
local structural index on first use; context calls need no graph or model key.

Start the stdio server with `julius mcp`. The `--full-tools` option exposes the
six inherited graph tools for compatibility, without the investigation recipes.

For example, discover `julius_file_api`, then invoke:

```json
{"operation":"julius_file_api","args":{"file":"src/index.ts"},"budget":800}
```

`budget` is 256 to 16000 `cl100k_base` tokens for the result text, including the
recovery envelope and excluding MCP framing. The default is 1200 when `budget`
is omitted. `delivery` is `selective` or `complete`. `focus` returns matching
lines for one literal, each trimmed to 160 characters, and retains the rest on
the handle. Fixed-string searches and exact symbol/file arguments
can supply automatic literals; semantic queries, regexes and impact seed paths
do not filter results by literal. `delivery: "complete"` with `budget` omitted returns
a one-line JSON header, a newline, and the original body; an explicit `budget`
still caps that body and returns `next`. Other omitted results retain an exact
local handle. Use `context.read` with `handle`, byte offsets `start` and `end`, `search`,
or `next.start`. `match: false` means the literal was absent. `anchorOmitted: true` means a
matching literal could not fit; recover it through `next.start`. Graph errors
remain `isError: true`, including when bounded. Each session receives usable
content; no cross-session suppression is assumed. Stats describe the payload
ledger and do not include discovery/schema or protocol costs. Discovery and
stats are small metadata responses, outside the capture ledger and result budget.

For sequential recovery, invoke `context.read` with the retained `handle`,
`start: next.start`, and `delivery: "complete"` without a budget. The response
contains a one-line JSON header and the requested bytes verbatim, avoiding
another JSON escape layer around the body. Its `start`, `end`, and `totalBytes`
refer to the original captured object; `handle` remains that object's digest.
For contiguous prefix previews, concatenate preview bytes and recovered suffix
before checking the digest. Matching-line deliveries expose `hits` and can be
trimmed or disjoint; recover those objects from `start: 0` before checking their
digest instead of treating the rendered lines as original prefix bytes.
Explicit `end` and `search` still restrict the range. Binary or split UTF-8
ranges use base64. An explicit budget still caps the complete read and supplies
the ordinary JSON envelope with a continuation cursor.

MCP exhaustive search renders single-line spans as `L12` instead of `L12-L12`.
A column heading explains `symbol kind location incomingEdges`.
Every symbol retains its file path, kind, span, count and matched source lines.
Ranking and truncation notices are retained.

## Experimental repository evidence

Set `evidence: true` on `julius_find_code` to request quoted excerpts from
current code and active learnings in the checkout:

```json
{"operation":"julius_find_code","args":{"query":"What is the parallel test policy and where does the harness share state?","evidence":true},"budget":300}
```

The pilot ranks files with the existing graph, ranks learnings with the
existing note matcher, and selects literal lines across both source types.
It reads each ranked file once and collapses identical note sections with the
same declared file scope. It uses up to eight matching learnings. With `in`,
a learning must name a touched path within that prefix. Sources come from a
single checkout. Personal learnings and cached branch learnings are excluded.

Each excerpt names its path and line range. Note ranges start at line 1 of
the parsed Markdown body, after front matter and outer whitespace. `under`
names its section. `| ` marks the start of each quoted line. If the results
exceed the budget, `More evidence` gives the `context.read` handle for the
full snapshot of matched files and note sections. Use `search` or byte
ranges for a particular excerpt and `delivery: "complete"` without a budget
to read the snapshot. A retained snapshot describes the checkout at the time
of the original query.

An explicit `focus` or `delivery: "complete"` applies existing economy
delivery to that snapshot. The pilot reads the current source text regardless
of `full`. Narrow the query or lower `limit` if the capture exceeds the 8 MiB
store limit. Ordinary `julius_find_code`, the CLI and `--full-tools` keep their
existing output. See [the pilot evaluation](context-evidence-pilot.md).

See [investigations](investigations.md) for change-impact and failure-localization
recipes, and [context economy](context-economy.md) for storage and accounting.

`context.capture` optionally accepts `compact: "tap"`, `"log"` or `"build"` in
its operation arguments. Compaction is off by default; graph results are not
compacted. For example:

```json
{"operation":"context.capture","args":{"content":"<captured TAP output>","compact":"tap"},"budget":1200}
```

The summary labels `delivery: "compacted"` and `omittedDetail: true`, retains an
original-byte handle, and fits the result budget. Small inputs remain verbatim;
non-shrinking or over-budget summaries use existing bounded capture. Complete
delivery and literal `focus` take precedence and bypass compaction. Recovery
never recompacts the original. See the context economy documentation for which
details each format summarizes and why recovery can outweigh initial savings.
