import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const root = process.cwd();
const scratch = mkdtempSync(join(tmpdir(), 'julius-package-'));
const smokeHome = join(scratch, 'home');
mkdirSync(smokeHome);
const npmCli = process.env.npm_execpath;
assert.ok(npmCli, 'Run this check with npm run release:smoke');
const pkg = JSON.parse(readFileSync('package.json', 'utf8'));
const env = { ...process.env, HOME: smokeHome, USERPROFILE: smokeHome, JULIUS_HOME: join(smokeHome, '.julius'), DO_NOT_TRACK: '1', CI: '1', JULIUS_NO_FETCH: '1' };
const run = (file, args, cwd = root) => execFileSync(file, args, {
  cwd, env, encoding: 'utf8', timeout: 180_000, maxBuffer: 8 * 1024 * 1024,
});
const npm = (args, cwd) => run(process.execPath, [npmCli, ...args], cwd);

try {
  const packOutput = npm(['pack', '--json', '--pack-destination', scratch]);
  // npm versions differ on whether prepare stdout precedes the JSON result.
  const jsonStart = packOutput.lastIndexOf('\n[');
  const [packed] = JSON.parse(jsonStart < 0 ? packOutput : packOutput.slice(jsonStart + 1));
  const paths = packed.files.map((file) => file.path);
  for (const required of ['dist/index.js', 'dist/index.d.ts', 'dist/bin/julius.js', 'dist/viewer/index.html', 'dist/graph/queries/php.scm', 'LICENSE', 'CREDITS.md', 'PROVENANCE.md', 'CHANGELOG.md', 'docs/upstream-changelog.md']) {
    assert.ok(paths.includes(required), `Missing package file: ${required}`);
  }
  for (const path of paths) {
    assert.ok(/^(?:dist\/|docs\/(?:assets\/|upstream-changelog\.md$)|(?:package\.json|README\.md|CHANGELOG\.md|CREDITS\.md|LICENSE|PROVENANCE\.md)$)/.test(path), `Unexpected package file: ${path}`);
    assert.ok(!/(?:^|\/)(?:\.env(?:\..*)?|\.npmrc|\.git|\.julius)(?:\/|$)/.test(path), `Private state in package: ${path}`);
  }
  const consumer = join(scratch, 'consumer');
  mkdirSync(consumer);
  writeFileSync(join(consumer, 'package.json'), '{"private":true,"type":"module"}\n');
  npm(['install', '--omit=dev', '--no-audit', '--no-fund', '--engine-strict', join(scratch, packed.filename)], consumer);
  const installed = join(consumer, 'node_modules', '@ruverd', 'julius');
  assert.equal(JSON.parse(readFileSync(join(installed, 'package.json'), 'utf8')).version, pkg.version);
  const nativeCheck = join(installed, '.julius-native-smoke.mjs');
  writeFileSync(nativeCheck, readFileSync(join(root, 'scripts', 'verify-native-parsers.mjs')));
  run(process.execPath, [nativeCheck], consumer);
  const cli = join(installed, 'dist', 'bin', 'julius.js');
  assert.equal(run(process.execPath, [cli, '--version'], consumer).trim(), pkg.version);

  const fixture = join(consumer, 'fixture');
  mkdirSync(fixture);
  run('git', ['init', '--quiet', fixture]);
  writeFileSync(join(fixture, 'hello.ts'), 'export function hello(): string { return "hello"; }\n');
  writeFileSync(join(fixture, 'example.rs'), 'pub fn wasm_hello() -> i32 { 42 }\n');
  writeFileSync(join(consumer, 'verify.mjs'), `
import assert from 'node:assert/strict';
import { Julius, Economy } from '@ruverd/julius';
assert.equal(typeof Economy, 'function');
const engine = new Julius();
await engine.graph(${JSON.stringify(fixture)});
const checked = await engine.checkGraph(${JSON.stringify(fixture)});
assert.equal(checked.ok, true, JSON.stringify(checked));
`);
  run(process.execPath, ['verify.mjs'], consumer);
  assert.match(run(process.execPath, [cli, 'skeleton', 'hello.ts', fixture], consumer), /function hello/);
  assert.match(run(process.execPath, [cli, 'skeleton', 'example.rs', fixture], consumer), /function wasm_hello\b/);
  console.log(`Package smoke passed: ${pkg.name}@${pkg.version}, ${paths.length} files, ${packed.size} bytes`);
  if (process.env.JULIUS_PACK_DESTINATION) {
    const { copyFileSync } = await import('node:fs');
    copyFileSync(join(scratch, packed.filename), resolve(process.env.JULIUS_PACK_DESTINATION, packed.filename));
  }
} finally {
  rmSync(scratch, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
}
