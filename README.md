# Julius

Julius builds a local graph of a repository and gives coding agents code search, call tracing, file APIs, dependency maps and shared learnings. It is an independent TypeScript fork of Trail-Code; see [source provenance](PROVENANCE.md) and the preserved MIT [license](LICENSE).

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

`julius init` configures the selected coding-agent integrations. Review `julius init --dry-run` first; `--no-global` limits setup to the repository. `julius mcp` serves the inherited navigation tools over stdio.

## Public API

```ts
import { Julius } from '@ruverd/julius';
const engine = new Julius();
await engine.init('/path/to/repo');
const drift = engine.check('/path/to/repo');
```

## External services

There is no configured Julius cloud service, telemetry collector or automatic npm check by default. Optional external features need explicit configuration; see [TELEMETRY.md](TELEMETRY.md). No upstream publishing credentials or deployment workflow are included.
