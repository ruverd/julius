/** Julius CLI identity, command layout, output and MCP contract. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { brand, tag } from "../src/brand.js";
import { commandInvokesJulius } from "../src/claude/session-metrics.js";
import { savingsLine, sumSavingsFooters } from "../src/context/savings.js";
import { homeEnv, tmpRepo } from "./helpers.js";

// --- the name itself ---

test("Julius identity is stable regardless of invocation environment", () => {
  assert.equal(brand({}), "julius");
  assert.equal(brand({ JULIUS_INVOKED_AS: "julius" }), "julius");
  assert.equal(brand({ JULIUS_INVOKED_AS: "something-else" }), "julius");
  assert.equal(tag({ JULIUS_INVOKED_AS: "julius" }), "[julius]");
  assert.equal(tag({}), "[julius]");
});

// --- isolated CLI fixtures ---

function scratchHome(): string {
  return mkdtempSync(join(tmpdir(), "julius-notice-"));
}

// --- what parses the output ---

test("multiple Julius savings footers are summed", () => {
  assert.equal(sumSavingsFooters("[julius] tokens saved ≈ 1,200 (80%)\n[julius] tokens saved ≈ 300 (50%)"), 1500);
});

test("supported Julius shell invocations count as retrievals", () => {
  assert.equal(commandInvokesJulius('julius ask "auth" --source'), true);
  assert.equal(commandInvokesJulius("npx -y @ruverd/julius grep foo"), true);
  assert.equal(commandInvokesJulius("cd x && julius callers run"), true);
  assert.equal(commandInvokesJulius("node dist/bin/julius.js ask x"), true);
  assert.equal(commandInvokesJulius("julius ask x"), true);
  assert.equal(commandInvokesJulius("mytrail ask x"), false);
  assert.equal(commandInvokesJulius("echo julius"), false);
});

// --- command layout, end to end ---

function run(name: "julius", args: string[], home: string, cwd = process.cwd(), extra: NodeJS.ProcessEnv = {}) {
  const r = spawnSync(process.execPath, ["--import", "tsx", join(process.cwd(), "src", "bin", `${name}.ts`), ...args], {
    cwd,
    encoding: "utf8",
    env: { ...process.env, ...homeEnv(home), DO_NOT_TRACK: "1", CLAUDECODE: undefined, JULIUS_INVOKED_AS: undefined, JULIUS_CLOUD: undefined, ...extra },
  });
  return { status: r.status, out: r.stdout, err: r.stderr };
}

function builtRepo(): string {
  const d = tmpRepo("julius-name");
  mkdirSync(join(d, "src"), { recursive: true });
  writeFileSync(join(d, "src", "a.ts"), "export function alpha(): number {\n  return beta();\n}\n");
  writeFileSync(join(d, "src", "b.ts"), "export function beta(): number {\n  return 1;\n}\n");
  spawnSync("git", ["init", "-q"], { cwd: d });
  return d;
}

test("julius --help groups the commands, and lists the workspace ones only once signing in is on", () => {
  const home = scratchHome();
  const r = run("julius", ["--help"], home);
  assert.equal(r.status, 0);
  for (const heading of ["Find code", "Team memory:", "Setup:", "CI:"]) assert.ok(r.out.includes(heading), heading);
  for (const c of ["note", "check", "team", "status"]) assert.match(r.out, new RegExp(`^  ${c} `, "m"), c);
  // Still run, just not listed: the brain's rules, corrections on skills, and signing in.
  for (const c of ["viz", "mcp", "stats", "watch", "connect", "julius", "push", "pull", "learn", "skills", "workspace", "login", "logout"])
    assert.doesNotMatch(r.out, new RegExp(`^  ${c} `, "m"), c);
  const on = run("julius", ["--help"], home, process.cwd(), { JULIUS_CLOUD: "1", JULIUS_URL: "https://cloud.example.test" });
  assert.ok(on.out.includes("Workspace"));
  for (const c of ["workspace", "login", "logout"]) assert.match(on.out, new RegExp(`^  ${c} `, "m"), c);
});

test("julius check is the team check, not the freshness check", () => {
  // Outside a git repo there is no diff to check; the freshness check is build --check.
  const r = run("julius", ["check", mkdtempSync(join(tmpdir(), "not-git-"))], scratchHome());
  assert.equal(r.status, 1);
  assert.match(r.err, /not a git repository/);
});

test("julius status puts the code map on one screen, and the workspace only once signing in is on", () => {
  const home = scratchHome();
  const d = builtRepo();
  run("julius", ["build", d], home);
  const r = run("julius", ["status", d], home);
  assert.equal(r.status, 0, r.err);
  assert.match(r.out, /^code map {4}✓ \d+ nodes · in sync with the code$/m);
  assert.doesNotMatch(r.out, /^workspace/m);
  const on = run("julius", ["status", d], home, process.cwd(), { JULIUS_CLOUD: "1", JULIUS_URL: "https://cloud.example.test" });
  assert.match(on.out, /^workspace {3}not connected · Claude offers a link once there are learnings to share$/m);
  const json = JSON.parse(run("julius", ["status", d, "--json"], home).out);
  assert.equal(json.workspace, null);
});

test("the savings footer uses Julius with explicit or default invocation identity", () => {
  const saved = { baselineChars: 40_000, files: 3 } as Parameters<typeof savingsLine>[1];
  const before = process.env.JULIUS_INVOKED_AS;
  try {
    delete process.env.JULIUS_INVOKED_AS;
    assert.match(savingsLine("short pack", saved), /^\[julius\] tokens saved ≈ /);
    process.env.JULIUS_INVOKED_AS = "julius";
    assert.match(savingsLine("short pack", saved), /^\[julius\] tokens saved ≈ /);
  } finally {
    if (before === undefined) delete process.env.JULIUS_INVOKED_AS;
    else process.env.JULIUS_INVOKED_AS = before;
  }
});

// --- MCP canonical tool names and aliases ---

async function mcpRpc(name: "julius", dir: string, messages: object[], expected: number): Promise<any[]> {
  const { spawn } = await import("node:child_process");
  const child = spawn(process.execPath, ["--import", "tsx", join(process.cwd(), "src", "bin", `${name}.ts`), "mcp", dir], {
    stdio: ["pipe", "pipe", "pipe"],
    env: { ...process.env, DO_NOT_TRACK: "1", JULIUS_INVOKED_AS: undefined },
  });
  const out: any[] = [];
  let buf = "";
  child.stdout.on("data", (d) => {
    buf += d.toString();
    let i;
    while ((i = buf.indexOf("\n")) !== -1) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (line) out.push(JSON.parse(line));
    }
  });
  for (const m of messages) child.stdin.write(`${JSON.stringify(m)}\n`);
  const deadline = Date.now() + 20000;
  while (out.length < expected && Date.now() < deadline) await new Promise((r) => setTimeout(r, 50));
  child.kill();
  return out;
}

test("Julius MCP advertises canonical tools and accepts its retrieval alias", async () => {
  const d = builtRepo();
  run("julius", ["build", d], scratchHome());
  const init = { jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-03-26", capabilities: {}, clientInfo: { name: "t", version: "0" } } };
  const list = { jsonrpc: "2.0", id: 2, method: "tools/list" };
  const call = (id: number, tool: string) => ({ jsonrpc: "2.0", id, method: "tools/call", params: { name: tool, arguments: { query: "beta" } } });

  const t = await mcpRpc("julius", d, [init, list, call(3, "julius_find_code"), call(4, "julius_ask")], 4);
  assert.equal(t.find((r) => r.id === 1)?.result.serverInfo.name, "julius");
  assert.match(t.find((r) => r.id === 1)?.result.instructions, /select:mcp__julius__julius_find_code,/);
  const names = t.find((r) => r.id === 2)?.result.tools.map((x: { name: string }) => x.name);
  assert.ok(names.includes("julius_find_code") && names.every((n: string) => n.startsWith("julius_")), String(names));
  for (const id of [3, 4]) assert.equal(t.find((r) => r.id === id)?.result.isError, false, `call ${id}`);


});

test("canonical tool names and aliases count as retrievals", async () => {
  const { canonicalToolName } = await import("../src/mcp/tool-names.js");
  const { isJuliusMcpTool } = await import("../src/claude/session-metrics.js");
  assert.equal(canonicalToolName("julius_find_code"), "julius_find_code");
  assert.equal(canonicalToolName("julius_ask"), "julius_find_code");
  assert.equal(isJuliusMcpTool("mcp__julius__julius_trace_calls"), true);
  assert.equal(isJuliusMcpTool("mcp__julius__julius_find_all"), true);
});
