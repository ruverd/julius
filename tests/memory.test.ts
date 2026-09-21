import { expect, test } from 'bun:test';
import { createHash } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { MemoryStore, type MemoryItem } from '../src/memory';
import { Database } from 'bun:sqlite';

function item(overrides: Partial<MemoryItem> = {}): MemoryItem {
  const content = overrides.content ?? 'Compiler error in dependency graph';
  return {
    id: 'fact-1', version: 1, projectId: 'alpha', snapshot: 'commit-a', content,
    contentSha256: createHash('sha256').update(content).digest('hex'),
    createdAt: new Date(Date.now() - 1000).toISOString(),
    expiresAt: new Date(Date.now() + 60000).toISOString(),
    provenance: 'observed', origin: 'log:17', ...overrides,
  };
}

test('retrieval requires matching project and snapshot, and invalidation is scoped', () => {
  const root = mkdtempSync(join(tmpdir(), 'julius-memory-'));
  const store = new MemoryStore(join(root, 'memory.db'));
  try {
    store.put(item());
    store.put(item({ projectId: 'beta', origin: 'log:18' }));
    expect(store.search('alpha', 'compiler error', { snapshot: 'commit-a' })).toHaveLength(1);
    expect(store.search('alpha', 'compiler error', { snapshot: 'commit-b' })).toHaveLength(0);
    expect(store.search('beta', 'compiler error', { snapshot: 'commit-a' })).toHaveLength(1);
    expect(store.invalidate('fact-1', 'alpha')).toBe(1);
    expect(store.search('alpha', 'compiler', { snapshot: 'commit-a' })).toHaveLength(0);
    expect(store.search('beta', 'compiler', { snapshot: 'commit-a' })).toHaveLength(1);
    expect(store.deleteProject('beta')).toBe(1);
    expect(store.search('beta', 'compiler', { snapshot: 'commit-a' })).toHaveLength(0);
  } finally { store.close(); rmSync(root, { recursive: true, force: true }); }
});

test('expiry, hash, immutable version and FTS query syntax', () => {
  const store = new MemoryStore(':memory:');
  try {
    store.put(item());
    expect(() => store.put(item())).toThrow();
    expect(() => store.put(item({ id: 'bad', contentSha256: 'bad' }))).toThrow('hash');
    store.put(item({ id: 'expired', expiresAt: new Date(Date.now() - 1).toISOString() }));
    expect(store.search('alpha', 'compiler', { snapshot: 'commit-a' })).toHaveLength(1);
    expect(store.purgeExpired('alpha')).toBe(1);
    expect(store.purgeExpired('alpha')).toBe(0);
    expect(store.search('alpha', '" OR *', { snapshot: 'commit-a' })).toEqual([]);
    expect(() => store.search('alpha', 'compiler', { snapshot: '' })).toThrow();
    expect(() => store.search('alpha', 'compiler', { snapshot: 'commit-a', limit: 101 })).toThrow();
  } finally { store.close(); }
});

test('search rejects altered content', () => {
  const root = mkdtempSync(join(tmpdir(), 'julius-memory-'));
  const path = join(root, 'memory.db');
  const store = new MemoryStore(path);
  try {
    store.put(item());
    const db = new Database(path);
    try { db.query('UPDATE memories SET content=? WHERE id=?').run('Compiler error in altered graph', 'fact-1'); }
    finally { db.close(); }
    expect(() => store.search('alpha', 'compiler', { snapshot: 'commit-a' })).toThrow('integrity');
  } finally { store.close(); rmSync(root, { recursive: true, force: true }); }
});
