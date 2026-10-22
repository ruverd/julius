import assert from 'node:assert/strict';
import { appendFileSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';

export function checkRelease({ pkg, lock, changelog, tag }) {
  assert.equal(pkg.name, '@ruverd/julius', 'Unexpected package name');
  assert.notEqual(pkg.private, true, 'Package must be public');
  assert.equal(pkg.publishConfig?.access, 'public', 'Scoped package must publish publicly');
  assert.equal(pkg.publishConfig?.registry, 'https://registry.npmjs.org/', 'Unexpected registry');
  assert.match(pkg.version, /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(?:alpha|beta|rc)\.(0|[1-9]\d*))?$/, 'Use X.Y.Z or X.Y.Z-{alpha,beta,rc}.N');
  assert.equal(lock.name, pkg.name, 'Lockfile package name differs');
  assert.equal(lock.version, pkg.version, 'Lockfile version differs');
  assert.equal(lock.packages?.['']?.name, pkg.name, 'Lockfile root name differs');
  assert.equal(lock.packages?.['']?.version, pkg.version, 'Lockfile root version differs');
  if (tag !== undefined) assert.equal(tag, `v${pkg.version}`, 'Git tag must match package version');

  const sections = [...changelog.matchAll(/^## (.+)\r?$/gm)];
  const releases = sections.filter((section) => section[1].trim() !== '[Unreleased]');
  assert.equal(releases[0]?.[1].trim(), pkg.version, 'Newest changelog release must match package version');
  const start = releases[0].index + releases[0][0].length;
  const next = sections.find((section) => section.index > releases[0].index);
  const notes = changelog.slice(start, next?.index).trim();
  assert.match(notes, /^- \S/m, 'Release notes must describe at least one change');
  return { version: pkg.version, distTag: pkg.version.includes('-') ? 'next' : 'latest', notes };
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const { values } = parseArgs({ options: { tag: { type: 'string' }, 'notes-file': { type: 'string' } } });
  const result = checkRelease({
    pkg: JSON.parse(readFileSync('package.json', 'utf8')),
    lock: JSON.parse(readFileSync('package-lock.json', 'utf8')),
    changelog: readFileSync('CHANGELOG.md', 'utf8'),
    tag: values.tag,
  });
  if (values['notes-file']) writeFileSync(values['notes-file'], `${result.notes}\n`);
  if (process.env.GITHUB_OUTPUT) {
    appendFileSync(process.env.GITHUB_OUTPUT, `version=${result.version}\ndist_tag=${result.distTag}\n`);
  }
  console.log(`Release verified: @ruverd/julius@${result.version} (${result.distTag})`);
}
