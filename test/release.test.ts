import assert from 'node:assert/strict';
import { test } from 'node:test';
// @ts-expect-error Release tooling runs directly as JavaScript.
import { checkRelease } from '../scripts/check-release.mjs';
// @ts-expect-error Release tooling runs directly as JavaScript.
import { needsPublication } from '../scripts/publish-release.mjs';

function metadata(version = '0.24.0') {
  return {
    pkg: { name: '@ruverd/julius', version, publishConfig: { access: 'public', registry: 'https://registry.npmjs.org/' } },
    lock: { name: '@ruverd/julius', version, packages: { '': { name: '@ruverd/julius', version } } },
    changelog: `# Changelog\n\n## [Unreleased]\n\n## ${version}\n\n### Added\n\n- Publish Julius.\n\n## 0.23.1\n\n- Older changes.\n`,
    tag: `v${version}`,
  };
}

test('release uses only current release notes and separates prereleases from latest', () => {
  assert.deepEqual(checkRelease(metadata()), { version: '0.24.0', distTag: 'latest', notes: '### Added\n\n- Publish Julius.' });
  for (const version of ['0.25.0-alpha.0', '0.25.0-beta.1', '0.25.0-rc.2']) {
    assert.equal(checkRelease(metadata(version)).distTag, 'next');
  }
});

test('release refuses mismatched tags, stale lockfiles, wrong package and missing notes', () => {
  const wrongTag = metadata();
  wrongTag.tag = 'v0.23.1';
  assert.throws(() => checkRelease(wrongTag), /Git tag/);
  const staleLock = metadata();
  staleLock.lock.packages[''].version = '0.23.1';
  assert.throws(() => checkRelease(staleLock), /Lockfile root version/);
  const wrongPackage = metadata();
  wrongPackage.pkg.name = 'julius';
  assert.throws(() => checkRelease(wrongPackage), /Unexpected package name/);
  const missingNotes = metadata();
  missingNotes.changelog = '# Changelog\n\n## 0.24.0\n\n## 0.23.1\n\n- Old notes.\n';
  assert.throws(() => checkRelease(missingNotes), /Release notes/);
  assert.throws(() => checkRelease({ ...metadata(), changelog: '# Changelog\n\n## 0.23.1\n\n- Old release.\n' }), /Newest changelog/);
});

test('release rejects malformed versions and unapproved prerelease channels', () => {
  for (const version of ['00.24.0', '0.24.0-rc.01', '0.24.0-preview.1', '0.24.0\nlatest']) {
    assert.throws(() => checkRelease(metadata(version)), /Use X.Y.Z/);
  }
});

test('publication retries only skip an identical published archive', () => {
  assert.equal(needsPublication('sha512-test', { status: 0, stdout: '"sha512-test"' }), false);
  assert.throws(() => needsPublication('sha512-test', { status: 0, stdout: '"sha512-other"' }), /different bytes/);
  assert.equal(needsPublication('sha512-test', { status: 1, stdout: '{"error":{"code":"E404"}}' }), true);
  assert.throws(() => needsPublication('sha512-test', { status: 1, stdout: '{"error":{"code":"E403"}}', stderr: 'Forbidden' }), /Registry lookup failed/);
  assert.throws(() => needsPublication('sha512-test', { status: null, error: new Error('timeout') }), /timeout/);
});
