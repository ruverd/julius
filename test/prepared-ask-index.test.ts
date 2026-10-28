import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { buildGraph } from "../src/graph/build.js";
import { ask } from "../src/ask/ask.js";
import { preparedAskDocs } from "../src/ask/prepared-index.js";
import { loadAskIndexCached, invalidateGraphCaches } from "../src/graph/load.js";
import { contextDirFor } from "../src/context/node-file.js";

test("prepared fields follow loader identity across edits, deletions and repeated queries", async () => {
  const dir = mkdtempSync(join(tmpdir(), "julius-prepared-index-"));
  try {
    const source = join(dir, "a.ts");
    writeFileSync(source, 'export function account() { return "originalneedle"; }\n');
    const removed = join(dir, "removed.ts");
    writeFileSync(removed, 'export function obsolete() { return "removedneedle"; }\n');
    await buildGraph(dir, { graphOnly: true });
    const outDir = contextDirFor(dir);
    const before = loadAskIndexCached(outDir);
    assert.ok(before);
    const bytesBefore = JSON.stringify(before);
    const prepared = preparedAskDocs(before);
    const queries = ["originalneedle", "removedneedle", "account", "zzzzunmatched"];
    const expected = queries.map(query => ask(dir, query, { source: true }));
    for (let rep = 0; rep < 3; rep++) {
      for (const [i, query] of queries.entries()) assert.deepEqual(ask(dir, query, { source: true }), expected[i]);
    }
    assert.equal(JSON.stringify(before), bytesBefore, "queries must not mutate the cached sidecar");
    assert.strictEqual(preparedAskDocs(before), prepared);
    writeFileSync(source, 'export function account() { return "updatedneedle"; }\n');
    rmSync(removed);
    await buildGraph(dir, { graphOnly: true });
    invalidateGraphCaches(outDir);
    const after = loadAskIndexCached(outDir);
    assert.ok(after);
    assert.notStrictEqual(after, before);
    assert.notStrictEqual(preparedAskDocs(after), prepared);
    assert.equal(ask(dir, "originalneedle", { graphRank: false }).hits.length, 0);
    assert.equal(ask(dir, "removedneedle", { graphRank: false }).hits.length, 0);
    assert.ok(ask(dir, "updatedneedle", { graphRank: false }).hits.some(hit => hit.title.startsWith("account")));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
