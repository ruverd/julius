# Julius

Julius builds a local graph of a repository and gives coding agents code search, call tracing, file APIs, dependency maps and shared learnings. It is an independent TypeScript fork of Trail-Code; see [source provenance](PROVENANCE.md) and the preserved MIT [license](LICENSE).

## Install from source

The package is **not published to npm**. Clone the default `main` branch, then
build and install the local tarball:

```sh
git clone https://github.com/ruverd/julius.git
cd julius
npm ci
npm run build
npm pack --pack-destination .
npm install -g ./ruverd-julius-0.23.1.tgz
julius install --dry-run
julius install
```

Setup detects Claude Code, Cursor, Codex and Grok configuration directories. Use
`julius install --hosts claude,cursor,codex,grok` to select them explicitly. Restart
or reconnect the client's MCP session after setup. The registered command uses
the installed Node executable and module path; it resolves the repository from
each MCP process's working directory. Keep that installation in place. If you
move Node or reinstall Julius at another path, run setup again.

`julius uninstall --global` undoes this setup, restoring replaced entries and
preserving unrelated edits. `--dry-run` previews both operations; `--home <path>`
selects an explicit home directory. Configuration tests and stdio tests cover
these formats; they do not establish live client compatibility or guarantee that
a client chooses Julius instead of its built-in tools.

See [installation and migration](docs/installation.md) for ownership conflicts,
rollback and copying existing Trail learnings.

## Coding without Julius commands

After setup, continue normal conversation in your coding client. The agent can
use Julius's experimental change-impact and failure-localization investigations
automatically through MCP. Julius builds the graph, combines local operations,
checks source freshness and returns bounded evidence. Recovery also uses MCP;
you do not need to invoke a CLI or slash command during coding.

Results retain uncertainty and source provenance. Tool selection remains the
host agent's decision. See [investigations and limitations](docs/investigations.md).

## Development

Requires Node.js 20 or later and npm.

```sh
npm ci
npm run build
npm test
node dist/bin/julius.js --help
```

The npm package name is `@ruverd/julius`; local packaging uses `npm pack`. Publication is a separate operation and is not configured by this repository.

## Local navigation

```sh
node dist/bin/julius.js build /path/to/repo
node dist/bin/julius.js ask "Where is authentication checked?" /path/to/repo
node dist/bin/julius.js map /path/to/repo
node dist/bin/julius.js callers handleRequest /path/to/repo
node dist/bin/julius.js skeleton src/index.ts /path/to/repo
node dist/bin/julius.js build --check /path/to/repo
```

The basic build and these navigation commands run locally without a model key. `--deep` opts into the inherited model-assisted analysis. Graph data lives in `.julius/cache/`; shared learnings live in `.julius/learnings/`; machine state lives in `~/.julius`.

`julius init` configures the selected coding-agent integrations. Review `julius init --dry-run` first; `--no-global` limits setup to the repository. `julius mcp` serves compact discovery and invocation over stdio; `--full-tools` explicitly exposes the six inherited graph tools.

`julius grep` accepts JavaScript regular expressions, including lookbehind and
backreferences; `--fixed` treats the pattern literally. Compilation and matching
each file have a 1,000 ms execution limit. Exceeding it aborts the search with an
error; simplify the pattern or use `--fixed`.

## Public API

```ts
import { Julius } from '@ruverd/julius';
const engine = new Julius();
await engine.graph('/path/to/repo'); // local structural analysis; no model calls
const drift = engine.check('/path/to/repo');
```

## External services

There is no configured Julius cloud service, telemetry collector or automatic npm check by default. Optional external features need explicit configuration; see [TELEMETRY.md](TELEMETRY.md). No upstream publishing credentials or deployment workflow are included.

### Recoverable context economy

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

Every command accepts `--repo <directory>` (default: current directory). Run executes
its argv once, without a shell, and returns the original exit status or signal.
Its response names separate stdout/stderr handles, status, and any capture limit.
The command's stdin is closed. Shell syntax is literal unless you explicitly run
a shell yourself.

Budgets count the entire rendered response, including handles, omission fields,
and recovery instructions, with the bundled offline `cl100k_base` encoding.
They are encoding counts, not universal model token counts. Small UTF-8 inputs
are returned verbatim with no handle or added envelope. Longer inputs and binary
inputs get SHA-256 handles for the exact original bytes. Preview envelopes label
UTF-8 or base64 content; byte ranges use an exclusive end offset. Search finds the
first exact UTF-8 byte sequence within the selected range. `--raw` explicitly
bypasses preview budgeting and returns exact bytes, including binary and CRLF.
Retrieving a missing, deleted, or corrupt object fails explicitly.

The current resource ceiling is **8 MiB per capture**, including combined stdout
and stderr for commands. File/stdin capture fails above that limit. Commands stop at a byte limit or
timeout and label the result `complete: false`; their handles recover only the
bytes captured, never the uncaptured remainder. Use `--max-bytes` to lower the
ceiling or `--timeout-ms` to change the 5-minute default (also the maximum).
Run budgets must be at least 300 tokens; other minimums depend on the rendered
handle envelope. Invalid and insufficient budgets fail explicitly. Retention is explicit: there is no automatic expiration or total-disk quota,
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

The exported API uses the same accounting and recovery rules:

```ts
import { Economy, economyTokens } from '@ruverd/julius';
const economy = new Economy('/path/to/repo');
const capture = await economy.capture(output, { budget: 512 }); // string or Uint8Array
if (capture.handle) {
  const recovered = await economy.read(capture.handle, { budget: 512, raw: true });
  // recovered.bytes contains exact bytes; recovered.text is UTF-8 or base64.
}
const command = await economy.run(['npm', 'test'], { budget: 512 });
const stats = await economy.stats();
```

For budgeted integration, deliver `result.text` exactly. `bytes`, `handle`, and
other returned metadata support callers and are outside the payload ledger;
count any additional transport wrappers separately. Budgeted `read()` returns
exact selected bytes in `bytes`, with start/end locations and total omitted bytes
in its rendered envelope. A budget can shorten that selected range further.

## Compact MCP

The default server advertises only `julius_discover` and `julius_call`, even in a
fresh repository. Discovery lists short operation descriptions; provide
`operation` to fetch just that operation's schema. The allowlist consists of the
six graph operations and `context.capture`, `context.read`, `context.stats`.
There is no shell or arbitrary code execution operation. Graph calls build the
local structural index on first use; context calls need no graph or model key.

For example, discover `julius_file_api`, then invoke:

```json
{"operation":"julius_file_api","args":{"file":"src/index.ts"},"budget":800}
```

`budget` is 256–16000 `cl100k_base` tokens for the result text, including the
recovery envelope and excluding MCP framing. The default is 1200 when `budget`
is omitted. `delivery` is `selective` or `complete`. `focus` windows a broader
result around one literal. `delivery: "complete"` with `budget` omitted returns
a one-line JSON header, a newline, and the original body; an explicit `budget`
still caps that body and returns `next`. Other omitted results retain an exact
local handle. Use `context.read` with `handle`, byte `start`/`end`, `search`,
or `next.start`. `match: false` with `matchCount` 0 means the literal was absent; with `matchCount` above 0 it was found but did not fit, so read `next`. Graph errors
remain `isError: true`, including when bounded. Each session receives usable
content; no cross-session suppression is assumed. Stats describe the payload
ledger and do not include discovery/schema or protocol costs. Discovery and
stats are small metadata responses, outside the capture ledger and result budget.

## Evidence and limitations

Run `npm run build && npm run benchmark:economy` for the offline experiment.
[Method and limitations](docs/economy-benchmark.md) explain the three separate
baselines and [checked-in JSON](docs/economy-benchmark.json) records reproducible
results. Follow-up retrieval and full recovery are charged; negative differences
and unknown totals remain visible. Fixed-fixture fact recovery does not measure
coding-task accuracy or provider billing. [Research notes](docs/research.md)
distinguish deployable local context techniques from model/server research.
