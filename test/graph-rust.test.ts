import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { extractFile, languageOf } from "../src/graph/extract.js";
import { buildGraph } from "../src/graph/build.js";
import { extractorStamp } from "../src/graph/extract-cache.js";
import { probeDrift } from "../src/graph/fingerprint.js";
import { rustExtractorStatus } from "../src/graph/rust.js";
import { ask } from "../src/ask/ask.js";

const addon = fileURLToPath(new URL("../native/extractor/extractor.node", import.meta.url));
const nativeAvailable = existsSync(addon);
const tsx = import.meta.resolve("tsx");
if (process.env.JULIUS_TEST_RUST === "1") assert.ok(nativeAvailable, "Rust CI requires npm run build:native to produce the addon");

async function backend<T>(mode: "rust" | "typescript", run: () => T | Promise<T>): Promise<T> {
  const previous = process.env.JULIUS_EXTRACTOR;
  process.env.JULIUS_EXTRACTOR = mode;
  try { return await run(); } finally {
    if (previous === undefined) delete process.env.JULIUS_EXTRACTOR; else process.env.JULIUS_EXTRACTOR = previous;
  }
}
function moduleFixture(body: string): string {
  const path = join(mkdtempSync(join(tmpdir(), "julius-rust-module-")), "extractor.cjs");
  writeFileSync(path, body);
  return path;
}

function childCheck(path: string, body: string): string {
  const base = new URL("../src/graph/", import.meta.url);
  const code = `
    import assert from 'node:assert/strict';
    import { extractFile } from ${JSON.stringify(new URL('extract.ts', base).href)};
    import { extractorStamp } from ${JSON.stringify(new URL('extract-cache.ts', base).href)};
    import { rustExtractorStatus } from ${JSON.stringify(new URL('rust.ts', base).href)};
    const source = "export function hello() { return 1; }";
    process.env.JULIUS_EXTRACTOR = 'typescript';
    const expected = extractFile('hello.ts', source, 'typescript');
    assert.equal(rustExtractorStatus().state, 'disabled');
    process.env.JULIUS_EXTRACTOR = 'rust';
    ${body}
  `;
  return execFileSync(process.execPath, ["--import", tsx, "--input-type=module", "-e", code], {
    env: { ...process.env, JULIUS_RUST_EXTRACTOR_PATH: path }, encoding: "utf8", timeout: 30_000,
  });
}

test("Rust backend is opt-in; absent and incompatible modules preserve extraction", () => {
  for (const path of [join(tmpdir(), "julius-no-such-rust-addon.node"), moduleFixture("module.exports={protocolVersion:2,extract(){throw Error('must not run')}}")]) {
    childCheck(path, `
      assert.deepEqual(extractFile('hello.ts', source, 'typescript'), expected);
      assert.equal(rustExtractorStatus().state, 'fallback');
      assert.ok(extractorStamp(), 'Known TypeScript fallback can be cached');
    `);
  }
});

test("Malformed native responses fall back and disable provenance reuse", () => {
  const packets = ["not-json", "{}", JSON.stringify([1, [], [[999, "contains", 0, null, null, null]]]),
    JSON.stringify([1, [["hello", "hello", "function", 0, 99999, 2, 1, 1, true, null]], []])];
  for (const packet of packets) {
    childCheck(moduleFixture(`module.exports={protocolVersion:1,extract(){return ${JSON.stringify(packet)}}}`), `
      assert.ok(extractorStamp());
      assert.deepEqual(extractFile('hello.ts', source, 'typescript'), expected);
      assert.equal(rustExtractorStatus().state, 'fallback');
      assert.equal(extractorStamp(), null, 'Failed addon must not certify a snapshot');
    `);
  }
});

test("Different native module bytes receive different extraction identities", () => {
  const first = moduleFixture("module.exports={protocolVersion:1,extract(){return '[1,[],[]]'}};");
  const second = moduleFixture("module.exports={protocolVersion:1,extract(){return '[1,[],[]]'}};\n");
  const identity = (path: string): string => childCheck(path, "assert.equal(rustExtractorStatus().state, 'ready'); console.log(extractorStamp());").trim();
  assert.notEqual(identity(first), identity(second));
});

test("Repository dotenv cannot select an executable addon path", () => {
  const dir = mkdtempSync(join(tmpdir(), 'julius-rust-dotenv-'));
  const marker = join(dir, 'executed');
  const path = moduleFixture(`require('node:fs').writeFileSync(${JSON.stringify(marker)}, 'bad'); module.exports={protocolVersion:1,extract(){return '[]'}};`);
  writeFileSync(join(dir, '.env'), `JULIUS_RUST_EXTRACTOR_PATH=${path}\n`);
  const code = `
    import { rustExtractorStatus } from ${JSON.stringify(new URL('../src/graph/rust.ts', import.meta.url).href)};
    await import(${JSON.stringify(import.meta.resolve('dotenv/config'))});
    process.env.JULIUS_EXTRACTOR = 'rust';
    rustExtractorStatus();
  `;
  const env = { ...process.env };
  delete env.JULIUS_RUST_EXTRACTOR_PATH;
  execFileSync(process.execPath, ['--import', tsx, '--input-type=module', '-e', code], { cwd: dir, env, timeout: 30_000 });
  assert.equal(existsSync(marker), false);
});

test("Rust matches all current TS/JS source and boundary fixtures", { skip: !nativeAvailable }, async () => {
  const root = fileURLToPath(new URL("../src/", import.meta.url));
  const sources: Array<[string, string]> = [
    ["empty.ts", ""],
    ["unicode.ts", '// 🦀 café\r\nexport function ação() { return "𐐀"; }\r\n'],
    ["view.tsx", "import { Button, click as handler } from './ui'; export const View = () => <Button onClick={handler}>🦀</Button>;"],
    ["shadow.ts", "import { Router as R, helper } from './core'; function f(x: R) { x.use(); return helper; } function g(helper: R) { helper.use(); }"],
    ["di.ts", "class C extends Base implements I { constructor(private readonly svc: Service) {} run() { this.svc.run(); } }"],
    ["dup.ts", "class C { m() {} } class C { m() {} } function f() {} function f() {}"],
    ["broken.ts", "export class Broken { m( { return imported; }\nconst x = () => {"],
    ["large.ts", Array.from({ length: 900 }, (_, i) => `export function f${i}() { return '🦀${i}'; }`).join("\n")],
    ["surrogate.ts", 'export function f() { return "\uD800"; }'],
    ["deep.ts", "const x = " + "(".repeat(150) + "1" + ")".repeat(150)],
    ["over-limit.ts", "//" + "x".repeat(4 * 1024 * 1024)],
  ];
  function visit(dir: string): void {
    for (const item of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, item.name);
      if (item.isDirectory()) visit(path);
      else if (["typescript", "tsx"].includes(languageOf(path) ?? "")) sources.push([relative(root, path), readFileSync(path, "utf8")]);
    }
  }
  visit(root);
  for (const [path, source] of sources) {
    const language = languageOf(path);
    assert.ok(language);
    const expected = await backend("typescript", () => extractFile(path, source, language));
    await backend("rust", () => {
      assert.deepEqual(extractFile(path, source, language), expected, path);
      assert.equal(rustExtractorStatus().state, "ready", `${path}: native path must remain usable`);
    });
  }
});

test("Backend selection invalidates cache/provenance and preserves full, incremental and query results", { skip: !nativeAvailable }, async () => {
  const dir = mkdtempSync(join(tmpdir(), "julius-rust-cache-"));
  const source = join(dir, "hello.ts");
  writeFileSync(source, 'export function hello() { return "before"; }\n');
  const baseline = await backend("typescript", async () => {
    const result = await buildGraph(dir, { reuse: false, graphOnly: true });
    return { outDir: result.contextDir, graph: readFileSync(result.graphPath, "utf8"), result: ask(dir, "hello", { source: true }), stamp: extractorStamp() };
  });
  await backend("rust", async () => {
    assert.notEqual(extractorStamp(), baseline.stamp);
    assert.equal(probeDrift(dir, baseline.outDir), null, "Switching backend must not reuse the old verification");
    const cold = await buildGraph(dir, { graphOnly: true });
    assert.equal(cold.parsed, 1); assert.deepEqual(cold.errors, []); assert.equal(cold.rustExtractor?.state, "ready");
    assert.equal(readFileSync(cold.graphPath, "utf8"), baseline.graph);
    assert.deepEqual(ask(dir, "hello", { source: true }), baseline.result);
    const unchanged = await buildGraph(dir, { graphOnly: true });
    assert.equal(unchanged.parsed, 0); assert.equal(unchanged.reused, 1);
    writeFileSync(source, 'export function hello() { return "after"; }\n');
    const edited = await buildGraph(dir, { graphOnly: true });
    assert.equal(edited.parsed, 1);
    const incremental = readFileSync(edited.graphPath, "utf8");
    const full = await buildGraph(dir, { reuse: false, graphOnly: true });
    assert.equal(readFileSync(full.graphPath, "utf8"), incremental);
  });
});
