import { execFileSync } from 'node:child_process';
import { copyFileSync, existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, '../../..');
const cargo = process.env.CARGO ?? (existsSync(join(homedir(), '.cargo/bin/cargo')) ? join(homedir(), '.cargo/bin/cargo') : 'cargo');
execFileSync(cargo, ['build', '--release', '--offline', '--manifest-path', join(here, 'Cargo.toml')], {
  cwd: here, stdio: 'inherit', env: { ...process.env, JULIUS_NODE_MODULES: join(repo, 'node_modules') },
});
const library = process.platform === 'darwin' ? 'libjulius_extractor_pilot.dylib' : 'libjulius_extractor_pilot.so';
if (process.platform === 'win32') throw new Error('This pilot has not been ported to Windows');
copyFileSync(join(here, 'target/release', library), join(here, 'extractor.node'));
console.log(join(here, 'extractor.node'));
