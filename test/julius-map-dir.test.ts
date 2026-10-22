import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { tmpRepo } from './helpers.js';
import { mapDirFor } from '../src/context/map-dir.js';
import { contextDirFor, ensureGitignored, ensureSearchable } from '../src/context/node-file.js';

test('all repositories use .julius/cache and explicit output overrides still win', () => {
  const repo = tmpRepo('map');
  assert.equal(mapDirFor(repo), join(repo, '.julius', 'cache'));
  assert.equal(contextDirFor(repo), mapDirFor(repo));
  assert.equal(contextDirFor(repo, '/elsewhere'), '/elsewhere');
});
test('default graph ignores stay inside .julius and preserve root user rules', () => {
  const repo = tmpRepo('map-ignore');
  writeFileSync(join(repo, '.gitignore'), 'node_modules/\n');
  ensureGitignored(repo, mapDirFor(repo));
  ensureSearchable(repo, mapDirFor(repo));
  assert.equal(readFileSync(join(repo, '.gitignore'), 'utf8'), 'node_modules/\n');
  assert.equal(existsSync(join(repo, '.ignore')), false);
  assert.match(readFileSync(join(repo, '.julius', '.gitignore'), 'utf8'), /^cache\/$/m);
});
