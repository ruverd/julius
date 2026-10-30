# Recoverable context economy

Julius keeps captured output in a local store and returns a bounded preview.
Recover the original bytes by handle when you need more detail.

## Commands

Capture noisy output locally, then retrieve exact bytes only when needed:

```sh
printf 'some output\n' | julius capture --budget 512
julius capture --file build.log --budget 512
julius run --budget 512 -- npm test
julius read sha256:<digest> --start 0 --end 1000 --budget 512
julius read sha256:<digest> --search 'error' --budget 512
julius read sha256:<digest> --raw > recovered.log
julius economy stats
```

### Optional output compaction

Opt in for known noisy output with `--compact tap`, `--compact log` or
`--compact build`. This is internal Julius code; no RTK or Caveman installation,
model or extra dependency is required. Compaction is off by default.

```sh
julius capture --file tests.tap --compact tap --budget 1200
julius run --compact tap --budget 1200 -- npm test
julius run --compact build --budget 1200 -- npm run build
```

TAP compaction counts consecutive minimal top-level passing records. Their
names and durations are omitted with an explicit notice. Failures, extra
diagnostics, nested records and SKIP/TODO records remain verbatim. Log and build
compaction collapse only consecutive identical lines, with additional-repeat
counts and preserved order. These modes do not infer a format from a command.
An unsuitable format simply produces no reduction.

Original stdout/stderr or captured bytes remain recoverable through the same
handles. Compacted content is a summary, not a prefix: recover from byte zero
instead of concatenating it with a suffix. Names, individual timings and full
event sequences may require recovery and can increase total traffic.

For capture, small inputs stay verbatim; a summary that exceeds the full response
budget falls back to the existing bounded preview. Custom API `preview` and
`compact` cannot be combined. For run, a complete compacted stream envelope is
used only when it is smaller in local token counts than the existing diagnostic
preview; otherwise the diagnostic preview remains. Incomplete captures and
timeouts retain existing preview behavior. Status, signal, capture limits,
binary recovery and accounting rules are unchanged. No speed or provider-cost
guarantee follows from selecting this option.

Every command accepts `--repo <directory>` (default: current directory). Run executes
its argv once, without a shell, and returns the original exit status or signal.
Its response names separate stdout/stderr handles, status, and any capture limit.
The command's stdin is closed. Shell syntax is literal unless you explicitly run
a shell yourself.

## Budgets and recovery

Budgets count the entire rendered response, including handles, omission fields,
and recovery instructions, with the bundled offline `cl100k_base` encoding.
They are encoding counts, not universal model token counts. Small UTF-8 inputs
are returned verbatim with no handle or added envelope. Longer inputs and binary
inputs get SHA-256 handles for the exact original bytes. Preview envelopes label
UTF-8 or base64 content; byte ranges use an exclusive end offset. Search finds the
first exact UTF-8 byte sequence within the selected range. `--raw` explicitly
bypasses preview budgeting and returns exact bytes, including binary and CRLF.
Retrieving a missing, deleted, or corrupt object fails explicitly.

## Capture limits and retention

The current resource ceiling is **8 MiB per capture**, including combined stdout
and stderr for commands. File and stdin capture fail above that limit. Commands stop at a byte limit or
timeout and label the result `complete: false`; their handles recover only the
bytes captured, never the uncaptured remainder. Use `--max-bytes` to lower the
ceiling or `--timeout-ms` to change the 5-minute default (also the maximum).
Run budgets must be at least 300 tokens; other minimums depend on the rendered
handle envelope. Invalid and insufficient budgets fail explicitly.

There is no automatic expiration or total-disk quota,
so the store can grow across captures. Stop active captures, then run
`julius economy clear --all --repo <directory>` to delete all economy payloads
and reset their ledger. The required `--all` flag makes this destructive intent
explicit; shared learnings remain untouched. Clear atomically detaches the old
store, preserving data created in a new store afterwards. In-flight operations
can fail during clearing, so coordinate cleanup with callers. Removal errors
are surfaced; an interrupted removal can leave an ignored
`.julius/economy-clearing-<id>/` directory for manual cleanup. Deleted handles
fail as missing; no content is silently expired. Stats refuse ledgers above 100,000 events rather than silently sampling.

Run previews select diagnostic lines (including nearby context), the beginning,
and the tail. They mark omissions and remain within the full response budget;
selection is heuristic, and exact handles remain the source of truth.

The store is repository-local at `.julius/economy/` and ignored by Git. Shared
`.julius/learnings/` stays Git-visible. Equal bytes reuse one object, but every
capture counts independently. Concurrent writers publish complete objects and
independent ledger events. A failed ledger write fails the operation; already
stored objects may remain available, and no successful delivery is claimed.

## Payload accounting

Tokenization uses bundled offline `tiktoken` WASM ranks. To bound pathological
BPE work, a whitespace or non-whitespace run longer than 4,096 UTF-16 units has
an **unknown** token count. Its bytes are still captured and recoverable. Stats
return `null` for any total containing an unknown count, including savings;
`accountedEvents`, `uncountedEvents`, `rawUncountedEvents`, and
`deliveredUncountedEvents` disclose coverage. No partial sum is presented as a
complete total. `economyTokens()` returns an exact count or throws an explicit
resource error for such input; raw retrieval succeeds and records unknown cost.
Rendered previews shrink until they can be counted exactly within budget.

For fully counted payloads, stats report raw payload tokens actually captured minus all rendered capture,
command, and retrieval deliveries. Retrieval adds cost without adding another
raw baseline, so savings can become negative. Binary payload accounting uses its
base64 representation. API metadata, protocol framing, schemas, requests, and
stats reports are excluded and disclosed. These are **local payload counts, not
provider measurements or invoice savings**. Economy operations never request a
model or access the network; a command you explicitly execute may do either.

## Public API

The exported API uses the same accounting and recovery rules:

```ts
import { Economy, economyTokens } from '@ruverd/julius';
const economy = new Economy('/path/to/repo');
const capture = await economy.capture(output, { budget: 512 }); // string or Uint8Array
const summary = await economy.capture(output, { budget: 1200, compact: 'tap' });
if (capture.handle) {
	const recovered = await economy.read(capture.handle, { budget: 512, raw: true });
	// recovered.bytes contains exact bytes; recovered.text is UTF-8 or base64.
}
const command = await economy.run(['npm', 'test'], { budget: 512 });
const compactCommand = await economy.run(['npm', 'test'], { budget: 1200, compact: 'tap' });
const stats = await economy.stats();
```

For budgeted integration, deliver `result.text` exactly. `bytes`, `handle`, and
other returned metadata support callers and are outside the payload ledger;
count any additional transport wrappers separately. Budgeted `read()` returns
exact selected bytes in `bytes`, with start/end locations and total omitted bytes
in its rendered envelope. A budget can shorten that selected range further.

See [compact MCP](compact-mcp.md) for agent delivery controls and
[the offline benchmark](economy-benchmark.md) for accounting methodology.
