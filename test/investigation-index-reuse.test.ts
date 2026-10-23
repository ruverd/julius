import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, readFileSync, rmSync, statSync, utimesSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { buildGraph } from '../src/graph/build.js';
import { runInvestigation } from '../src/investigation/index.js';
import { contextDirFor } from '../src/context/node-file.js';
import { wiringPath } from '../src/graph/write.js';
import { fingerprintPath } from '../src/graph/fingerprint.js';
import { execFileSync } from 'node:child_process';
import { realNativeRequire, setNativeRequireForTest } from '../src/graph/native.js';

test('first investigation reuses a verified persisted index with automatic refresh disabled', async () => {
  const root = mkdtempSync(join(tmpdir(), 'julius-index-reuse-'));
  const previous = process.env.JULIUS_NO_REFRESH;
  try {
    writeFileSync(join(root, 'core.ts'), 'export function hello() { return 1; }\n');
    writeFileSync(join(root, 'caller.ts'), 'import { hello } from "./core";\nexport function caller() { return hello(); }\n');
    await buildGraph(root);
    const graph = wiringPath(contextDirFor(root));
    const before = readFileSync(graph, 'utf8');
    process.env.JULIUS_NO_REFRESH = '1';
    const result = await runInvestigation(root, { recipe: 'change-impact', paths: ['core.ts'] });
    assert.ok(result.evidence.some(item => item.name === 'caller' && item.role === 'dependent'));
    assert.equal(result.reused, false);
    assert.equal(readFileSync(graph, 'utf8'), before);
  } finally {
    if (previous === undefined) delete process.env.JULIUS_NO_REFRESH;
    else process.env.JULIUS_NO_REFRESH = previous;
    rmSync(root, { recursive: true, force: true });
  }
});

async function fixture(run: (root: string) => Promise<void>) {
  const root = mkdtempSync(join(tmpdir(), 'julius-index-reuse-'));
  const previous = process.env.JULIUS_NO_REFRESH;
  delete process.env.JULIUS_NO_REFRESH;
  try {
    execFileSync('git', ['init', '--quiet', root]);
    writeFileSync(join(root, 'core.ts'), 'export function hello() { return 1; }\n');
    writeFileSync(join(root, 'caller.ts'), 'import { hello } from "./core";\nexport function caller() { return hello(); }\n');
    await buildGraph(root);
    await run(root);
  } finally {
    if (previous === undefined) delete process.env.JULIUS_NO_REFRESH;
    else process.env.JULIUS_NO_REFRESH = previous;
    rmSync(root, { recursive: true, force: true });
  }
}
const request = { recipe: 'change-impact', paths: ['core.ts'] } as const;
const investigate = (root: string) => runInvestigation(root, { ...request, paths: [...request.paths] });

test('index verification detects source edits with preserved size and mtime', async () => {
  await fixture(async root => {
    const file = join(root, 'core.ts'), before = statSync(file);
    writeFileSync(file, 'export function hello() { return 2; }\n');
    utimesSync(file, before.atime, before.mtime);
    process.env.JULIUS_NO_REFRESH = '1';
    await assert.rejects(investigate(root), /refresh is disabled/);
    delete process.env.JULIUS_NO_REFRESH;
    assert.ok((await investigate(root)).evidence.some(item => item.excerpt.includes('return 2')));
  });
});

test('graph corruption is rejected even after a report was cached', async () => {
  await fixture(async root => {
    await investigate(root);
    const file = wiringPath(contextDirFor(root));
    const graph = JSON.parse(readFileSync(file, 'utf8'));
    graph.edges = [];
    writeFileSync(file, JSON.stringify(graph));
    process.env.JULIUS_NO_REFRESH = '1';
    await assert.rejects(investigate(root), /refresh is disabled/);
    delete process.env.JULIUS_NO_REFRESH;
    assert.ok((await investigate(root)).evidence.some(item => item.name === 'caller'));
  });
});

test('configuration and ignore membership changes invalidate index verification', async () => {
  for (const change of [
    (root: string) => writeFileSync(join(root, 'tsconfig.json'), '{"compilerOptions":{"strict":true}}'),
    (root: string) => writeFileSync(join(root, '.gitignore'), 'caller.ts\n'),
  ]) {
    await fixture(async root => {
      change(root);
      process.env.JULIUS_NO_REFRESH = '1';
      await assert.rejects(investigate(root), /refresh is disabled/);
    });
  }
});

test('legacy and mismatched-extractor fingerprints require verification by rebuilding', async () => {
  for (const legacy of [true, false]) {
    await fixture(async root => {
      const path = fingerprintPath(contextDirFor(root));
      const fp = JSON.parse(readFileSync(path, 'utf8'));
      if (legacy) delete fp.verification;
      else fp.extractor = 'different-extractor';
      writeFileSync(path, JSON.stringify(fp));
      process.env.JULIUS_NO_REFRESH = '1';
      await assert.rejects(investigate(root), /refresh is disabled/);
      delete process.env.JULIUS_NO_REFRESH;
      assert.ok((await investigate(root)).evidence.some(item => item.name === 'caller'));
      assert.ok(JSON.parse(readFileSync(path, 'utf8')).verification);
    });
  }
});

test('verified index retains explicit directory scope', async () => {
  await fixture(async root => {
    mkdirSync(join(root, 'src'));
    writeFileSync(join(root, 'src', 'core.ts'), 'export function scoped() { return 1; }\n');
    await buildGraph(root, { onlyDirs: ['src'] });
    process.env.JULIUS_NO_REFRESH = '1';
    const report = await runInvestigation(root, { recipe: 'change-impact', paths: ['src/core.ts'] });
    assert.equal(report.coverage.sourceFiles, 1);
    assert.equal(report.coverage.scope, 'src');
    assert.ok(report.evidence.every(item => item.path.startsWith('src/')));
  });
});

test('configuration changing during a build is not certified', async () => {
  await fixture(async root => {
    const config = join(root, 'tsconfig.json');
    writeFileSync(config, '{"compilerOptions":{"strict":true}}');
    await buildGraph(root, { onProgress: progress => {
      if (progress.phase === 'parse') writeFileSync(config, '{"compilerOptions":{"strict":false}}');
    } });
    process.env.JULIUS_NO_REFRESH = '1';
    await assert.rejects(investigate(root), /refresh is disabled/);
  });
});

test('WASM stand-ins remain usable and are verified within their current process', async () => {
  const root = mkdtempSync(join(tmpdir(), 'julius-fallback-reuse-'));
  try {
    setNativeRequireForTest(id => {
      if (id === 'tree-sitter-typescript') throw new Error('Fixture native parser unavailable');
      return realNativeRequire(id);
    });
    writeFileSync(join(root, 'core.ts'), 'export function hello() { return 1; }\n');
    const first = await investigate(root);
    assert.ok(first.evidence.some(item => item.name === 'hello'));
    assert.equal((await investigate(root)).reused, true);
    const fp = JSON.parse(readFileSync(fingerprintPath(contextDirFor(root)), 'utf8'));
    assert.equal(fp.verification, undefined, 'a repaired native installation must verify this graph again');
  } finally {
    setNativeRequireForTest(null);
    rmSync(root, { recursive: true, force: true });
  }
});
