import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

// This module ships inside the package at <pkgRoot>/dist/claude/paths.js. Resolving julius's
// own CLI and sibling scripts relative to THIS file — not the project dir — is what makes the
// hooks work when julius is installed as a dependency in someone else's repo (where
// <projectDir>/dist/ does not exist). In julius's own repo it resolves to ./dist all the same.
const CLAUDE_DIR = dirname(fileURLToPath(import.meta.url));

/** Absolute path to the julius CLI (`<pkgRoot>/dist/cli.js`), resolved from this module. */
export function juliusCliPath(): string {
  return join(CLAUDE_DIR, '..', 'cli.js');
}

/** Absolute path to this package's `dist/claude` dir. Baked into the generated shims at
 * init time as their primary resolution candidate, so the statusline/hooks find julius
 * without runtime guesswork — correct regardless of how Node was installed. */
export function claudeDistDir(): string {
  return CLAUDE_DIR;
}

/** Absolute path to a sibling script in the claude dir (e.g. `sync-run.js`). */
export function claudeScriptPath(name: string): string {
  return join(CLAUDE_DIR, name);
}
