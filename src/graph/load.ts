/**
 * File-identity-keyed in-process cache over the two readers `ask()` calls on every
 * query: the wiring graph (`readGraph`) and the ask sidecar (`readAskIndex`).
 * `julius ask` re-parses these from disk on every invocation; in a long-lived
 * process — the MCP server, or `julius ask` invoked repeatedly in one process —
 * that means re-parsing the same ~tens-of-MB JSON on every tool call.
 *
 * Keyed by path, device, inode, ctime, mtime and size. Atomic replacement and
 * in-place writes invalidate it even if size and mtime are preserved. A missing
 * file returns null and is never cached — the
 * next call re-stats, so a file created after a prior miss is picked up
 * immediately (no negative caching).
 *
 * A miss verifies identity again after parsing; concurrent replacement retries
 * once, then returns null rather than caching data under the wrong identity.
 *
 * Dependency-free by design: this module imports only `node:fs`, `./write.js`,
 * and `../ask/index-file.js`, so it can be imported from both `ask.ts` and
 * `mcp/tools.ts` without creating an import cycle.
 */
import { statSync } from "node:fs";
import { readGraph, wiringPath } from "./write.js";
import { readAskIndex, askIndexPath, type AskIndex } from "../ask/index-file.js";
import type { GraphV1 } from "./types.js";

interface FileIdentity {
  mtimeMs: number;
  ctimeMs: number;
  ino: number;
  dev: number;
  size: number;
}

interface CacheEntry<T> extends FileIdentity { value: T | null }

const graphCache = new Map<string, CacheEntry<GraphV1>>();
const askIndexCache = new Map<string, CacheEntry<AskIndex>>();

/** Real parses performed (cache misses), not cache hits — exported for tests
 * so the invalidation contract can be pinned down without spying on `fs`. */
export const __parseCount = { graph: 0, askIndex: 0 };

/** Test-only: zero the counters (module state persists across a test file). */
export function __resetParseCounts(): void {
  __parseCount.graph = 0;
  __parseCount.askIndex = 0;
}

function statOf(path: string): FileIdentity | null {
  try {
    const s = statSync(path);
    return { mtimeMs: s.mtimeMs, ctimeMs: s.ctimeMs, ino: s.ino, dev: s.dev, size: s.size };
  } catch {
    return null;
  }
}

function sameFile(a: FileIdentity, b: FileIdentity): boolean {
  return a.mtimeMs === b.mtimeMs && a.ctimeMs === b.ctimeMs && a.ino === b.ino && a.dev === b.dev && a.size === b.size;
}

function loadCached<T>(
  cache: Map<string, CacheEntry<T>>,
  path: string,
  parse: () => T | null,
  onParse: () => void,
): T | null {
  const st = statOf(path);
  if (!st) {
    // Missing file: don't negatively cache, and drop any stale entry so a
    // subsequently-created file at the same path is re-parsed, not served
    // from a cache keyed to the old (mtime, size).
    cache.delete(path);
    return null;
  }
  const cached = cache.get(path);
  if (cached && sameFile(cached, st)) {
    return cached.value;
  }
  let before = st;
  for (let attempt = 0; attempt < 2; attempt++) {
    onParse();
    const value = parse();
    const after = statOf(path);
    if (!after) break;
    if (sameFile(before, after)) {
      cache.set(path, { ...after, value });
      return value;
    }
    before = after;
  }
  cache.delete(path);
  return null;
}

/** Cached `readGraph(wiringPath(outDir))` — same null-on-missing/unparseable
 * semantics, re-reads when the wiring file's identity changes.
 * Returns a shared cached reference; callers must not mutate the returned graph. */
export function loadGraphCached(outDir: string): GraphV1 | null {
  const path = wiringPath(outDir);
  return loadCached(graphCache, path, () => readGraph(path), () => {
    __parseCount.graph++;
  });
}

/** Cached `readAskIndex(outDir)` — same semantics, keyed on the sidecar identity.
 * Returns a shared cached reference; callers must not mutate the returned index. */
export function loadAskIndexCached(outDir: string): AskIndex | null {
  const path = askIndexPath(outDir);
  return loadCached(askIndexCache, path, () => readAskIndex(outDir), () => {
    __parseCount.askIndex++;
  });
}

/**
 * Drop the cached graph + sidecar for `outDir`, forcing the next load to re-read.
 *
 * The `(mtimeMs, size)` key above is a good invalidator for a build that happened
 * in *another* process, but not for one this process just performed: the
 * pre-query auto-refresh (`refresh.ts`) rewrites the graph and then immediately
 * queries it, and on a filesystem with coarse mtime resolution a same-tick rewrite
 * of the same size would be served from the stale entry. Callers that rebuild must
 * therefore invalidate explicitly rather than trust the clock.
 */
export function invalidateGraphCaches(outDir: string): void {
  graphCache.delete(wiringPath(outDir));
  askIndexCache.delete(askIndexPath(outDir));
}
