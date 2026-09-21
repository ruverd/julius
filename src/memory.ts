import { Database } from 'bun:sqlite';
import { createHash } from 'node:crypto';
import { chmodSync, existsSync, lstatSync, mkdirSync, realpathSync } from 'node:fs';
import { dirname, parse, resolve, sep } from 'node:path';

export type MemoryProvenance = 'observed' | 'inferred' | 'user_confirmed';
export interface MemoryItem {
  id: string;
  version: number;
  projectId: string;
  snapshot: string;
  content: string;
  contentSha256: string;
  createdAt: string;
  expiresAt: string;
  provenance: MemoryProvenance;
  origin: string;
}
export interface MemoryHit extends MemoryItem { score: number }

function validDate(value: string): boolean {
  return /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(value) &&
    Number.isFinite(Date.parse(value)) && new Date(value).toISOString() === value;
}

export class MemoryStore {
  private readonly db: Database;
  constructor(path: string) {
    if (path !== ':memory:') {
      const file = resolve(path);
      const parent = dirname(file);
      const parts = parent.slice(parse(parent).root.length).split(sep).filter(Boolean);
      const first = parts.shift();
      let current = first ? realpathSync(resolve(parse(parent).root, first)) : parse(parent).root;
      for (const part of parts) {
        current = resolve(current, part);
        if (!existsSync(current)) mkdirSync(current, { mode: 0o700 });
        const stat = lstatSync(current);
        if (stat.isSymbolicLink() || !stat.isDirectory()) throw new Error('Unsafe memory directory');
      }
      path = resolve(current, file.slice(parent.length + 1));
      if (existsSync(path) && lstatSync(path).isSymbolicLink()) throw new Error('Unsafe memory path');
    }
    this.db = new Database(path, { create: true });
    if (path !== ':memory:') chmodSync(path, 0o600);
    this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA secure_delete=ON;
      CREATE TABLE IF NOT EXISTS memories (
        id TEXT NOT NULL, version INTEGER NOT NULL, project_id TEXT NOT NULL,
        snapshot TEXT NOT NULL, content TEXT NOT NULL, content_sha256 TEXT NOT NULL,
        created_at TEXT NOT NULL, expires_at TEXT NOT NULL, provenance TEXT NOT NULL,
        origin TEXT NOT NULL, invalidated INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(project_id,id,version));
      CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(content, content='memories', content_rowid='rowid');
      CREATE TRIGGER IF NOT EXISTS memory_ai AFTER INSERT ON memories BEGIN
        INSERT INTO memory_fts(rowid,content) VALUES(new.rowid,new.content);
      END;
      CREATE TRIGGER IF NOT EXISTS memory_ad AFTER DELETE ON memories BEGIN
        INSERT INTO memory_fts(memory_fts,rowid,content) VALUES('delete',old.rowid,old.content);
      END;`);
  }
  put(item: MemoryItem): void {
    if (!item.id || !item.projectId || !item.snapshot || !item.origin || !Number.isSafeInteger(item.version) || item.version < 1) throw new Error('Invalid memory identity');
    if (typeof item.content !== 'string' || Buffer.byteLength(item.content) > 1024 * 1024) throw new Error('Invalid memory content');
    if (createHash('sha256').update(item.content).digest('hex') !== item.contentSha256) throw new Error('Memory content hash mismatch');
    if (!validDate(item.createdAt) || !validDate(item.expiresAt) || Date.parse(item.expiresAt) <= Date.parse(item.createdAt)) throw new Error('Invalid memory expiry');
    if (!['observed', 'inferred', 'user_confirmed'].includes(item.provenance)) throw new Error('Invalid memory provenance');
    this.db.query(`INSERT INTO memories(id,version,project_id,snapshot,content,content_sha256,created_at,expires_at,provenance,origin)
      VALUES(?,?,?,?,?,?,?,?,?,?)`).run(item.id,item.version,item.projectId,item.snapshot,item.content,item.contentSha256,item.createdAt,item.expiresAt,item.provenance,item.origin);
  }
  search(projectId: string, query: string, options: { snapshot: string; limit?: number }): MemoryHit[] {
    if (!projectId || !options?.snapshot) throw new Error('Project and snapshot required');
    if (typeof query !== 'string' || query.length > 256) throw new Error('Invalid query');
    const limit = options.limit ?? 20;
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) throw new Error('Invalid limit');
    const words = query.normalize('NFKC').match(/[\p{L}\p{N}_]+/gu)?.slice(0, 16) ?? [];
    if (words.length === 0) return [];
    const expression = words.map(word => `"${word.replaceAll('"', '""')}"`).join(' AND ');
    const hits = this.db.query(`SELECT m.id,m.version,m.project_id AS projectId,m.snapshot,m.content,
      m.content_sha256 AS contentSha256,m.created_at AS createdAt,m.expires_at AS expiresAt,
      m.provenance,m.origin,bm25(memory_fts) AS score FROM memory_fts
      JOIN memories m ON m.rowid=memory_fts.rowid
      WHERE memory_fts MATCH ? AND m.project_id=? AND m.snapshot=? AND m.invalidated=0 AND m.expires_at>?
      ORDER BY score,m.id,m.version LIMIT ?`).all(expression,projectId,options.snapshot,new Date().toISOString(),limit) as MemoryHit[];
    for (const hit of hits) {
      if (createHash('sha256').update(hit.content).digest('hex') !== hit.contentSha256) throw new Error('Memory content integrity mismatch');
    }
    return hits;
  }
  invalidate(id: string, projectId: string): number {
    if (!id || !projectId) throw new Error('Identity required');
    const count = (this.db.query('SELECT count(*) AS n FROM memories WHERE id=? AND project_id=? AND invalidated=0').get(id,projectId) as {n:number}).n;
    this.db.query('UPDATE memories SET invalidated=1 WHERE id=? AND project_id=? AND invalidated=0').run(id,projectId);
    return count;
  }
  deleteProject(projectId: string): number {
    if (!projectId) throw new Error('Project required');
    const count = (this.db.query('SELECT count(*) AS n FROM memories WHERE project_id=?').get(projectId) as {n:number}).n;
    this.db.query('DELETE FROM memories WHERE project_id=?').run(projectId);
    return count;
  }
  purgeExpired(projectId: string): number {
    if (!projectId) throw new Error('Project required');
    const count = (this.db.query('SELECT count(*) AS n FROM memories WHERE project_id=? AND expires_at<=?').get(projectId,new Date().toISOString()) as {n:number}).n;
    this.db.query('DELETE FROM memories WHERE project_id=? AND expires_at<=?').run(projectId,new Date().toISOString());
    try { this.db.exec('PRAGMA wal_checkpoint(TRUNCATE)'); } catch { /* checkpoint is best effort */ }
    return count;
  }
  close(): void { this.db.close(); }
}
