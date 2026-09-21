import { test, expect } from 'bun:test';
import { mkdtempSync, rmSync, symlinkSync, writeFileSync, readFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { ArtifactStore } from '../src/artifacts';

test('artifacts isolate projects and can be removed', () => {
  const root = mkdtempSync(join(tmpdir(), 'julius-artifacts-'));
  try {
    const store = new ArtifactStore(root);
    const item = store.put('one', 'original');
    expect(store.get('one', item.id)).toBe('original');
    expect(() => store.get('two', item.id)).toThrow();
    store.delete('one', item.id);
    expect(() => store.get('one', item.id)).toThrow();
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('invalid paths, expiry and symlink directories are rejected', async () => {
  const root = mkdtempSync(join(tmpdir(), 'julius-artifacts-'));
  try {
    const store = new ArtifactStore(root);
    expect(() => store.get('one', '../escape')).toThrow();
    const item = store.put('one', 'short lived', { ttlMs: 1 });
    await Bun.sleep(5);
    expect(() => store.get('one', item.id)).toThrow('expired');
    expect(store.purgeExpired('one')).toBe(1);
    expect(store.purgeExpired('one')).toBe(0);
    const hash = createHash('sha256').update('other').digest('hex');
    const outside = mkdtempSync(join(tmpdir(), 'julius-outside-'));
    try {
      symlinkSync(outside, join(root, hash));
      expect(() => store.put('other', 'secret')).toThrow('symlink');
    } finally { rmSync(outside, { recursive: true, force: true }); }
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('same-size corruption and invalid metadata cannot be restored', () => {
  const root = mkdtempSync(join(tmpdir(), 'julius-artifacts-'));
  try {
    const store = new ArtifactStore(root);
    const item = store.put('one', 'original');
    const dir = join(root, createHash('sha256').update('one').digest('hex'));
    writeFileSync(join(dir, `${item.id}.txt`), 'altered!');
    expect(() => store.get('one', item.id)).toThrow('integrity');
    const metadataPath = join(dir, `${item.id}.json`);
    const metadata = JSON.parse(readFileSync(metadataPath, 'utf8'));
    metadata.expiresAt = 'not-a-date';
    writeFileSync(metadataPath, JSON.stringify(metadata));
    expect(() => store.get('one', item.id)).toThrow('metadata');
    expect(existsSync(metadataPath)).toBe(true);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
