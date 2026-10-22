<p align="center">
  <img src="docs/assets/julius-hero.png" alt="Black-and-white ASCII portrait of Julius holding a floating data cube, with connected cubes, a thick white outline, and a transparent background." width="960">
</p>

<h1 align="center">Julius</h1>

<p align="center">
  <strong>"That's 50,000 tokens of context. Do you think tokens grow on trees?"</strong><br>
  Local code intelligence and recoverable context for coding agents.
</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#benchmarks">Benchmarks</a> ·
  <a href="#documentation">Documentation</a>
</p>

Your agent needs to find a function, follow its callers, or locate a failure in a
long log. Julius builds a local repository graph and returns evidence within a
context budget. Omitted output stays on disk, ready to recover when the agent
needs it.

Structural indexing and context recovery run locally, without a model key.
After MCP setup, keep asking normal coding questions. The agent discovers and
calls Julius through two tools.

## Install

Requires **Node.js 20+** and npm.

```sh
npm install -g @ruverd/julius
julius install --dry-run
julius install
```

To update an existing installation:

```sh
npm install -g @ruverd/julius@latest
julius --version
```

Restart or reconnect the client's MCP session after updating. Run `julius install`
again if the Node executable or installed package path changes. To select an
exact version, use `npm install -g @ruverd/julius@0.24.0`.

### Install from source

```sh
git clone https://github.com/ruverd/julius.git
cd julius
npm ci
npm run build
npm pack --pack-destination .
npm install -g ./ruverd-julius-0.24.0.tgz
julius install --dry-run
julius install
```

Setup detects Claude Code, Cursor, Codex, and the native xAI Grok CLI. To select
hosts explicitly, use `julius install --hosts claude,cursor,codex,grok`.
Restart or reconnect the client's MCP session after setup.

Then open a repository in your coding client and ask:

```text
What calls handleRequest, and what could this change affect?
Find the code near this failure: "expected 403 received 200".
```

The host must start MCP in the repository's working directory. Julius indexes
that repository on demand. Tool selection and permissions belong to the host
agent; configuration and stdio tests do not establish live client compatibility.

Keep the installed Node executable and package path in place. If either moves,
run setup again. To undo global setup, run `julius uninstall --global`.
See [installation and migration](docs/installation.md) for rollback, ownership
conflicts, and repository-specific setup with `julius init`.

## How it works

Julius gives agents a structural view of the code and control over how much
evidence enters the conversation.

| When the agent needs to… | Julius provides… |
| --- | --- |
| Find code | Ranked search, file signatures, and source locations |
| Understand dependencies | Call tracing, reference edges, and repository maps |
| Investigate a change or failure | Experimental change-impact and literal failure-localization reports |
| Read a large result | Bounded previews, literal focus, or explicit complete delivery |
| Recover omitted evidence | Local SHA-256 handles, byte ranges, and exact-text search |
| Keep repository knowledge | Shared learnings under `.julius/learnings/` |

The default MCP server advertises `julius_discover` and `julius_call`. The agent
discovers an operation's schema, invokes it, and retrieves more evidence as needed.
Results default to a 1,200-token text budget using the offline `cl100k_base`
encoding. Explicit complete delivery without a budget returns all captured bytes.

Graph evidence has limits. Dynamic calls, ignored files, and unsupported syntax
can be missing. A dependency is a candidate for investigation, not proof of a
breakage. See [investigations and limitations](docs/investigations.md).

## Benchmarks

**49.3% fewer protocol tokens** in the recorded offline comparison with the
[pinned upstream executable](PROVENANCE.md). This result describes a specific
synthetic task mix, not a prediction of your bill.

The measured source commit is `625693a046ebc011d2c29ec09e0a03385a1b2a46`, prepared for
`0.24.1`. The [report](docs/strategy/recovery-impact-comparison.json) records
source, compiled-output and lockfile hashes; subsequent documentation updates
preserve the measured source tree.

![Offline MCP comparison: pinned upstream uses 463,332 tokens; Julius uses 235,134, a 49.3% reduction. Local cl100k_base protocol counts, not provider usage.](docs/assets/context-benchmark.svg)

The experiment runs ten synthetic evidence tasks in TypeScript, Python, and Go,
with three repetitions per task and language. Each compared arm has 90 executions.
Counts include MCP initialization, discovery, invocation, and every recovery call.
The Julius arm follows the recorded selective/complete policy, including complete
range recovery after a preview.

Complete recovery avoids repeated pages. Composed impact reports group every
identity while retaining detailed evidence locally:

| Task, summed across nine executions | Pinned upstream | Julius |
| --- | ---: | ---: |
| Retrieve one required fact | 78,903 | 8,274 |
| Request complete output explicitly | 78,903 | 63,789 |
| Recover all output without a hint | 78,903 | 78,291 |
| Investigate impact with a composed report | 15,186 | 13,062 |
| **All ten task types** | **463,332** | **235,134** |

These are offline `cl100k_base` counts over JSON-RPC NDJSON traffic. No model runs,
provider billing, or coding-task accuracy were measured. Aggregate savings do not
hold for every language: Python's no-hint recovery still costs more than upstream.
Local timing is uncontrolled; the checks verify synthetic evidence recovery,
not the correctness or speed of a code change.

Read the [method, all task results, limitations, and reproduction steps](docs/strategy/recovery-impact-comparison.md)
or inspect the [recorded JSON](docs/strategy/recovery-impact-comparison.json).
The [earlier comparison](docs/strategy/performance-comparison.md) remains available.
Regenerate this chart with `node scripts/render-readme-benchmark.mjs`.

## Local navigation

The CLI also works directly, without an MCP client or a model key:

```sh
julius build /path/to/repo
julius ask "Where is authentication checked?" --source /path/to/repo
julius map /path/to/repo
julius callers handleRequest /path/to/repo
julius skeleton src/index.ts /path/to/repo
julius build --check /path/to/repo
```

Graph data lives in `.julius/cache/`, shared learnings in `.julius/learnings/`,
and machine state in `~/.julius`. `--deep` explicitly enables model-assisted
analysis. Run `julius --help` for the command list.

`julius grep` accepts JavaScript regular expressions, including lookbehind and
backreferences. Use `--fixed` for literal text. Compilation and matching each file
have a 1,000 ms limit; exceeding it aborts the search with an error.

### Recoverable context economy

Keep noisy command output out of the conversation until you need it:

```sh
julius run --budget 512 -- npm test
julius capture --file build.log --budget 512
julius read sha256:<digest> --search 'error' --budget 512
julius economy stats
```

`run` executes its command once and preserves its exit status or signal. Handles
recover captured bytes exactly, up to the 8 MiB capture ceiling. Follow-up reads
add to delivery cost, so savings can become negative. Local payload counts are
not provider measurements. See [context economy](docs/context-economy.md) for
limits, retention, accounting, and the exported API.

### Public API

```ts
import { Julius } from '@ruverd/julius';

const engine = new Julius();
await engine.graph('/path/to/repo');
const drift = engine.check('/path/to/repo');
```

## Documentation

| Guide | What it covers |
| --- | --- |
| [Installation and migration](docs/installation.md) | Host setup, rollback, ownership, and migration |
| [Investigations](docs/investigations.md) | Change impact, failure localization, freshness, and coverage |
| [Compact MCP](docs/compact-mcp.md) | Discovery, budgets, delivery controls, and recovery |
| [Context economy](docs/context-economy.md) | Capture, command output, storage, accounting, and API |
| [Executable comparison](docs/strategy/performance-comparison.md) | Recorded benchmark results and counterexamples |
| [Fixture benchmark](docs/economy-benchmark.md) | Offline payload accounting and exact-byte recovery |
| [Research notes](docs/research.md) | Local context techniques and research boundaries |
| [External services](TELEMETRY.md) | Optional configuration and network behavior |

There is no default Julius cloud service, telemetry collector, or automatic npm
check. Optional external services require explicit configuration. A command you
explicitly run through Julius can access the network.

## Development

```sh
npm ci
npm run build
npm test
node dist/bin/julius.js --help
```

Run `npm run benchmark:economy` after building for the separate offline fixture
experiment. See [releasing](docs/releasing.md) for versioning, release checks,
npm trusted publishing and recovery. Julius release notes live in
[CHANGELOG.md](CHANGELOG.md).

## License and provenance

Julius is an independent TypeScript fork of Trail-Code, distributed under the
[MIT license](LICENSE). Upstream copyright and credits are preserved. See
[source provenance](PROVENANCE.md) for the pinned source, fork history, and the
archived earlier Julius product.
