# Selective delivery

Date: 2026-10-22. Status: approved design, not implemented.

Julius already stores a large tool result under `.julius/economy` and returns a bounded preview plus a `context.read` handle. This design adds a deterministic choice between three deliveries, and an offline experiment that must pass before the result is treated as an improvement. No learned policy, no network, no smaller default budget.

## Policy

`selectDelivery` lives in `src/economy/delivery.ts`. `callCompact` applies it. Inputs are the operation name, operation args, optional `julius_call` fields `delivery`, `focus`, and `budget`. Output mode is `full`, `targeted`, or `fixed`.

`julius_call` gains two optional arguments:

- `delivery`: `selective` or `complete`
- `focus`: string, length 1 through 512

`budget` stays an optional integer from 256 through 16000. An omitted `budget` is distinct from an explicit `1200`.

Decision order:

1. `delivery: "complete"` and `budget` omitted: `full`.
2. `delivery: "complete"` and `budget` present: the number caps the body. The response is incomplete and carries `next`.
3. `delivery: "selective"`, or a selector literal exists: `targeted`. Omitted `budget` means 1200.
4. Otherwise: `fixed`. Omitted `budget` means 1200. This covers `julius_repo_map`, `context.capture` without `focus`, and `context.stats`.

Explicit `delivery` wins over inference and over `focus`. `delivery: "complete"` ignores `focus`.

Selector literals, in order: `focus`, `query`, `pattern`, `symbol`, `file`, `path`, then each `paths` entry. `in`, `depth`, `limit`, `max_dirs`, `content`, and `recipe` are not selectors. The first non-empty string in that list is the only literal, except `paths`: when no earlier field is set, every path is a literal. A missing earlier literal does not fall through. `delivery: "selective"` with no literal uses fixed truncation and labels the envelope `targeted`.

## Envelopes

Bytes are still stored with the existing SHA-256 handle and 8 MB ceiling. Offsets are bytes. `next` is `{ start, end }` for the unread tail, where `end` is `totalBytes`. A prefix before a middle window is read with `context.read` from `0` to the delivered `start`. `next` is null when the delivered slice reaches `totalBytes`.

### Full

One header line, a newline, then the original body bytes verbatim. The body is not placed inside a JSON string.

```json
{"delivery":"complete","handle":"sha256:…","totalBytes":0,"omittedBytes":0,"incomplete":false,"next":null,"format":"utf8"}
```

`format` is `utf8` or `base64`, using the current representation rule. A capped complete response uses the same framing: the longest UTF-8-safe prefix whose header, newline, and prefix fit the budget. `incomplete` is true and `next.start` is the prefix length.

When the body token count is unavailable because a whitespace or non-whitespace run exceeds 4096 UTF-16 units, store the bytes and return only the header: `incomplete: true`, `omittedBytes` equal to `totalBytes`, `next` at `{ start: 0, end: totalBytes }`. The delivered token count stays null.

### Targeted text

One JSON object. Find the literal with a byte search, non-overlapping. The anchor is the earliest match. For several paths, the earliest path match wins ties by path order. `matchCount` counts matches of the literals that were eligible. The object lists at most eight later match starts in `offsets`.

The slice starts as the literal itself and expands to enclosing lines, then outward by UTF-8 code points, while the stringified object stays within the budget. The delivered `content` contains the literal. A literal that cannot fit yields `match: false` and empty `content`.

On a hit the object carries `delivery: "targeted"`, `handle`, `match: true`, `matchCount`, `offsets`, `start`, `end`, `totalBytes`, `omittedBytes`, `content`, `format`, `recover`, and `next` only when a tail remains. `recover` is `{ operation: "context.read", args: { handle }, instruction }` and tells the agent to call `julius_call` with a search or byte range.

On a miss, `match` is false, `content` is empty, `omittedBytes` equals `totalBytes`, and `next` is `{ start: 0, end: totalBytes }`. The head of the result is not copied in. `isError` is false.

### Investigation

`deliverInvestigation` keeps `coverage` and `unknowns` equal to the full report. Evidence whose `path`, `name`, `id`, or `excerpt` contains an eligible literal comes first. Only matching evidence occupies the budget. Oversized matches shrink with the current halving loop. If one matching item still exceeds the budget, the generic targeted window over the stored report JSON is used. Zero matches produce `evidence: []`, `match: false`, `omittedEvidence`, the handle, and `recover`.

### Fixed

Today's head truncation and investigation halving remain. The envelope adds `delivery: "fixed"` and `next` when the body is cut.

### context.read

Without `search`, the read is the contiguous range from `start` and stops where the budget stops. `next` is the tail after the delivered end. A search miss returns `Search text not found` with `isError: true`.

## Errors and accounting

Invalid `delivery`, an out-of-range `budget`, a capture over 8 MB, a bad handle, a corrupt object, a bad range, and an empty search keep the current failures. An 8 MB capture stores nothing. A budget too small for the header or envelope fails with the current minimum-envelope error.

`match: false` is a successful tool result. The ledger stores `rawTokens` and `deliveredTokens`. An unknown count stays null. A recovery read still records raw tokens as 0, so negative savings stay visible.

## Instructions and scope

Update `COMPACT_INSTRUCTIONS`, `INVESTIGATION_WORKFLOW`, the README budget paragraph, and `docs/investigations.md`. The agent instruction, in English, says:

- Put one required fact in the operation literal (`query`, `pattern`, `symbol`, `path`, `file`, or `paths`), or pass `focus` when a broader result must be windowed around that fact.
- Pass `delivery: "complete"` and omit `budget` when every item in the result is required.
- Follow `next` with `context.read` at `next.start`.
- Treat `match: false` as an absent literal and search the handle with another literal.
- Call the tools. Do not ask the user to run Julius commands.

Unchanged in this slice: `julius read`, the default 1200 cap for `targeted` and `fixed`, the inherited full tool list, handoff, and new composition. There is no learned router and no 400-token default. The public `delivery` enum has no `fixed` value. The experiment reaches fixed behavior by calling the renderer with mode `fixed` from the harness.

## Experiment gate

New frozen manifest: `scripts/experiments/delivery-policy-tasks.json`. Do not edit `scripts/experiments/local-comparison-tasks.json`. The runner is `scripts/experiments/delivery-policy.ts`, imported by `npm test` the same way as the idea probes. One TypeScript repository. Provider usage and coding-task accuracy stay null. Counts are offline `cl100k_base` tokens over every message, including recovery and failed lookups.

Manifest:

- `functions`: 180
- `target`: 78
- marker text `BENCH_MARKER_078: retry_limit=7`, placed so a head preview of 1200 tokens does not contain it
- two functions whose names share the prefix `Retry`; the required fact is the second occurrence
- absent literal `BENCH_MARKER_MISSING`
- one non-source file `vendor/readme.txt`

The `npm test` fixture must produce a raw body above 1200 tokens. A body that fits fails the test.

Arms, on the same bytes: always complete (raw body), fixed (harness mode `fixed`, budget 1200), and policy (public rules). Cells:

| Cell | Call | Quality |
| --- | --- | --- |
| One fact | `context.capture` of the full listing, `focus` set to the target marker, `budget` omitted | Marker is in the first response |
| All, with flag | `delivery: "complete"`, `budget` omitted | All 180 markers, and the body SHA-256 equals the stored object |
| All, without flag | same listing, no `delivery` and no `focus` | Tokens and truncation are reported. This cell stays out of the savings decision |
| Absent hint | `focus` is `BENCH_MARKER_MISSING`, then one `context.read` with the frozen target | First response has `match: false` and lacks the fact; the second response has the fact; both calls count |
| Ambiguous symbol | `focus` is the shared prefix | The required fact is the second match. The anchor window may contain only the first. Later offsets are read, up to 8, and every read counts. Quality passes when the fact appears in one of those responses |
| Unindexed | investigation delivery | `coverage` and `unknowns` equal the stored report; `vendor/readme.txt` is absent from evidence. A unit test injects `unindexedFiles: 2` and requires that number to survive |
| Mixed | one-fact call, then complete call | Both quality checks; tokens are the sum |

Decision function:

- any policy quality failure: `reject-quality`
- a null token count: `inconclusive`
- one-fact, all-with-flag, or mixed policy tokens greater than or equal to the fixed arm: `reject-no-saving`
- otherwise: `advance-offline-only`

The report also records always-complete tokens. The decision ignores that arm. `advance-offline-only` does not authorize a 400-token default or a billing claim. Negative savings remain in the report.

Unit tests cover `selectDelivery`, the window, `match: false`, non-overlapping `next` reassembly including a multibyte boundary, investigation with zero matches, full delivery with a handle, an explicit budget on `complete`, an uncountable body, and the new instruction text.
