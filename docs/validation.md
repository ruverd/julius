# Validation and release gates

This file records implementation scope, not a benchmark claim.

Final local validation: 51 tests passed (184 assertions), TypeScript checks passed, native compilation passed, and compiled executable smoke passed. The smoke exercised repeat import, signed marginal arithmetic, unknown financial savings, and HTML/CSV export.

## Automated validation

Run `bun test`, `bun run typecheck`, and `bun run build`. Tests cover provider cache normalization, event idempotence, explicit aliases, reconciliation, negative/marginal transforms, incomplete counters, request windows, artifact isolation/expiry/integrity, conservative optimization, importers, HTML/CSV escaping, and CLI lifecycle. Multi-process tests race eight reservations of 30 against a budget of 100 and require exactly three successes.

The integration suite uses temporary directories and synthetic events. It does not execute paid model requests. Fixture compatibility is not verified native client compatibility.

## Platform status

Initial development validation: macOS arm64, Bun 1.3.13. Native executable compilation and local smoke checks are required before each release. CI is configured for macOS and Linux but a configuration file is not evidence of a successful CI run. WSL and native Windows are not certified.

Local discovery during implementation found Claude Code 2.1.278 and codex-cli 0.154.0. Version detection passed; native usage capture and rewriting were not tested. Ollama at `127.0.0.1:11434` did not respond, so the live-runtime gate remains open. Fixture tests verify runtime discovery parsing separately.

## Open product gates

- Two installed clients must complete non-destructive official-interface usage tests with exact versions and coverage limitations recorded.
- A live runtime discovery test must identify installed and loaded state without inferring hardware fitness.
- Signed distributions need clean-machine install/uninstall and update/rollback validation.
- A controlled task benchmark must freeze repository snapshots, task success criteria, model/runtime versions, cache state, and valid baseline configurations.
- Evaluation must include Portuguese/English tasks, failures, retries, overhead, latency, and confidence intervals. Local string reduction does not demonstrate agent quality.
- The 20% input-reduction target is a product hypothesis, never a measured result in this repository.

## Official references checked during implementation

- [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
- [Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Claude Code hooks](https://code.claude.com/docs/en/hooks)
- [Codex hooks](https://developers.openai.com/codex/hooks)
- [Ollama installed models](https://docs.ollama.com/api/tags)
- [Ollama loaded models](https://docs.ollama.com/api/ps)
- [Bun single-file executables](https://bun.sh/docs/bundler/executables)

Consult references again when implementing a native adapter. An API described in documentation does not certify this implementation against an installed client.
