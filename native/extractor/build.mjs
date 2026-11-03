import { execFileSync } from 'node:child_process';
import { copyFileSync, existsSync, renameSync } from 'node:fs';
import { createRequire } from 'node:module';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
if (!['darwin', 'linux'].includes(process.platform)) throw new Error('Rust extraction currently supports macOS and Linux; use the default TypeScript backend on this platform');
const require = createRequire(import.meta.url);
const cargo = process.env.CARGO ?? (existsSync(join(homedir(), '.cargo/bin/cargo')) ? join(homedir(), '.cargo/bin/cargo') : 'cargo');
// Resolve each package independently: npm may hoist dependencies above this package.
const core = dirname(require.resolve('tree-sitter/package.json'));
const grammar = dirname(require.resolve('tree-sitter-typescript/package.json'));
execFileSync(cargo, ['build', '--release', '--locked', ...(process.argv.includes('--online') ? [] : ['--offline']), '--manifest-path', join(here, 'Cargo.toml')], {
  cwd: here, stdio: 'inherit', env: { ...process.env, JULIUS_TREE_SITTER: core, JULIUS_TS_GRAMMAR: grammar },
});
const library = process.platform === 'darwin' ? 'libjulius_extractor.dylib' : 'libjulius_extractor.so';
const target = join(here, 'extractor.node');
copyFileSync(join(resolve(here, process.env.CARGO_TARGET_DIR || 'target'), 'release', library), `${target}.tmp`);
renameSync(`${target}.tmp`, target);
console.log(`Built optional Rust extractor: ${target}`);
