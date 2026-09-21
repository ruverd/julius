import { randomUUID, createHash } from 'node:crypto';
import { mkdirSync, writeFileSync, readFileSync, unlinkSync, lstatSync, realpathSync, existsSync, openSync, closeSync, fstatSync, readdirSync, constants } from 'node:fs';
import { join, resolve } from 'node:path';

const MAX_BYTES = 1024 * 1024;
const MAX_TTL_MS = 30 * 24 * 60 * 60 * 1000;

export interface ArtifactMetadata { id: string; projectId: string; bytes: number; sha256: string; createdAt: string; expiresAt: string }

function readProtected(path: string): string {
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const stat = fstatSync(fd);
    if (!stat.isFile() || stat.size > MAX_BYTES + 1024 || (stat.mode & 0o077) !== 0) throw new Error('Unsafe artifact file');
    return readFileSync(fd, 'utf8');
  } finally { closeSync(fd); }
}

function validMetadata(value: unknown, projectId: string, id: string): value is ArtifactMetadata {
  if (typeof value !== 'object' || value === null) return false;
  const m = value as Record<string, unknown>;
  const created = typeof m.createdAt === 'string' ? Date.parse(m.createdAt) : NaN;
  const expires = typeof m.expiresAt === 'string' ? Date.parse(m.expiresAt) : NaN;
  return m.id === id && m.projectId === projectId && Number.isSafeInteger(m.bytes) &&
    typeof m.bytes === 'number' && m.bytes >= 0 && m.bytes <= MAX_BYTES &&
    typeof m.sha256 === 'string' && /^[a-f0-9]{64}$/.test(m.sha256) &&
    Number.isFinite(created) && Number.isFinite(expires) && expires > created && expires - created <= MAX_TTL_MS;
}

export class ArtifactStore {
  private readonly root: string;
  constructor(root: string) {
    const requestedRoot = resolve(root);
    mkdirSync(requestedRoot, { recursive: true, mode: 0o700 });
    if (lstatSync(requestedRoot).isSymbolicLink()) throw new Error('Artifact root is a symlink');
    this.root = realpathSync(requestedRoot);
  }
  private paths(projectId: string, id: string) {
    if (!projectId || projectId.length > 256) throw new Error('Invalid project ID');
    if (!/^[a-f0-9-]{36}$/.test(id)) throw new Error('Invalid artifact ID');
    const dir = join(this.root, createHash('sha256').update(projectId).digest('hex'));
    if (realpathSync(this.root) !== this.root) throw new Error('Artifact root changed');
    if (existsSync(dir) && lstatSync(dir).isSymbolicLink()) throw new Error('Artifact directory is a symlink');
    mkdirSync(dir, { recursive: true, mode: 0o700 });
    if (lstatSync(dir).isSymbolicLink()) throw new Error('Artifact directory is a symlink');
    return { body: join(dir, `${id}.txt`), meta: join(dir, `${id}.json`) };
  }
  put(projectId: string, content: string, options: { ttlMs?: number } = {}): ArtifactMetadata {
    const bytes = Buffer.byteLength(content);
    if (bytes > MAX_BYTES) throw new Error('Artifact too large');
    const ttlMs = options.ttlMs ?? 24 * 60 * 60 * 1000;
    if (!Number.isSafeInteger(ttlMs) || ttlMs <= 0 || ttlMs > MAX_TTL_MS) throw new Error('Invalid TTL');
    const id = randomUUID();
    const now = Date.now();
    const metadata = { id, projectId, bytes, sha256: createHash('sha256').update(content).digest('hex'), createdAt: new Date(now).toISOString(), expiresAt: new Date(now + ttlMs).toISOString() };
    const { body, meta } = this.paths(projectId, id);
    writeFileSync(body, content, { flag: 'wx', mode: 0o600 });
    writeFileSync(meta, JSON.stringify(metadata), { flag: 'wx', mode: 0o600 });
    return metadata;
  }
  get(projectId: string, id: string): string {
    const { body, meta } = this.paths(projectId, id);
    const metadata: unknown = JSON.parse(readProtected(meta));
    if (!validMetadata(metadata, projectId, id)) throw new Error('Invalid artifact metadata');
    if (Date.parse(metadata.expiresAt) <= Date.now()) throw new Error('Artifact expired');
    const content = readProtected(body);
    if (Buffer.byteLength(content) !== metadata.bytes || createHash('sha256').update(content).digest('hex') !== metadata.sha256) throw new Error('Artifact integrity mismatch');
    return content;
  }
  delete(projectId: string, id: string): void {
    const { body, meta } = this.paths(projectId, id);
    const metadata: unknown = JSON.parse(readProtected(meta));
    if (!validMetadata(metadata, projectId, id)) throw new Error('Invalid artifact metadata');
    readProtected(body);
    unlinkSync(body); unlinkSync(meta);
  }
  purgeExpired(projectId: string): number {
    const dir = join(this.root, createHash('sha256').update(projectId).digest('hex'));
    if (!existsSync(dir)) return 0;
    if (lstatSync(dir).isSymbolicLink()) throw new Error('Artifact directory is a symlink');
    let removed = 0;
    for (const name of readdirSync(dir)) {
      if (!/^[a-f0-9-]{36}\.json$/.test(name)) continue;
      const id = name.slice(0, -5);
      const { body, meta } = this.paths(projectId, id);
      const metadata: unknown = JSON.parse(readProtected(meta));
      if (!validMetadata(metadata, projectId, id)) throw new Error('Invalid artifact metadata');
      if (Date.parse(metadata.expiresAt) > Date.now()) continue;
      readProtected(body);
      unlinkSync(body); unlinkSync(meta); removed++;
    }
    return removed;
  }
}
