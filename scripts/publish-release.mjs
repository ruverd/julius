import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFileSync, spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { basename, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { checkRelease } from './check-release.mjs';

export function needsPublication(integrity, response) {
  if (response.error) throw response.error;
  const body = JSON.parse(response.stdout);
  if (response.status === 0) {
    assert.equal(body, integrity, 'Published version has different bytes; use a new version');
    return false;
  }
  assert.equal(body?.error?.code, 'E404', `Registry lookup failed: ${response.stderr}`);
  return true;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const pkg = JSON.parse(readFileSync('package.json', 'utf8'));
  const release = checkRelease({
    pkg,
    lock: JSON.parse(readFileSync('package-lock.json', 'utf8')),
    changelog: readFileSync('CHANGELOG.md', 'utf8'),
    tag: process.env.RELEASE_TAG,
  });
  const archive = resolve(process.argv[2] ?? '');
  assert.equal(basename(archive), `ruverd-julius-${release.version}.tgz`, 'Pass the tested release archive');
  const integrity = `sha512-${createHash('sha512').update(readFileSync(archive)).digest('base64')}`;
  const npmCli = process.env.npm_execpath;
  assert.ok(npmCli, 'Run with npm run release:publish -- <archive.tgz>');
  const response = spawnSync(process.execPath, [npmCli, 'view', `${pkg.name}@${release.version}`, 'dist.integrity', '--json', '--registry=https://registry.npmjs.org/'], {
    encoding: 'utf8', timeout: 30_000,
  });
  if (needsPublication(integrity, response)) {
    execFileSync(process.execPath, [npmCli, 'publish', archive, '--access', 'public', '--provenance', '--tag', release.distTag, '--registry=https://registry.npmjs.org/'], { stdio: 'inherit' });
  } else {
    console.log(`Already published with matching integrity: ${pkg.name}@${release.version}`);
  }
}
