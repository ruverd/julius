/** Agent-facing navigation hints use Julius commands; promotional tallies stay suppressed. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { BRAND_ENV } from "../src/brand.js";
import { weakMatchNudge } from "../src/claude/format.js";
import { hasSavingsTally } from "../src/claude/tally.js";
import type { SessionState } from "../src/claude/state.js";
import { savingsTurnNudge } from "../src/context/savings.js";
import { zeroHitNote } from "../src/search/grep-cli.js";
import type { GrepResult } from "../src/search/grep.js";

/** Supported command hints emitted to the agent. */
const JULIUS_COMMAND = /\bjulius (ask|build|grep|callers|skeleton|map|blast|telemetry)\b|\[julius\]/;

function under<T>(name: "julius", fn: () => T): T {
  const saved = process.env[BRAND_ENV];
  process.env[BRAND_ENV] = name;
  try {
    return fn();
  } finally {
    if (saved === undefined) delete process.env[BRAND_ENV];
    else process.env[BRAND_ENV] = saved;
  }
}

const grepMiss = { pattern: "x", filesSearched: 3, truncated: { files: 1 } } as unknown as GrepResult;

test("hints the agent reads name julius's commands under julius", () => {
  const lines = under("julius", () => [
    weakMatchNudge({ nudges: 0 } as SessionState, 0.1)!,
    zeroHitNote(grepMiss),
  ]);
  for (const line of lines) {
    assert.match(line, JULIUS_COMMAND, line);
    assert.match(line, /julius/, line);
  }
});

test("navigation hints retain Julius spelling while promotional savings are suppressed", () => {
  assert.match(under("julius", () => weakMatchNudge({ nudges: 0 } as SessionState, 0.1)!), /^\[julius\] .*`julius ask "<your task>" --source`/);
  assert.equal(under("julius", () => savingsTurnNudge(1200)), "");
});

test("historical Julius tally text remains recognizable", () => {
  assert.equal(hasSavingsTally("🌱 julius saved ~12k tokens (~$0.04) this turn, 3 calls"), true);
  assert.equal(hasSavingsTally("🌱 julius saved ~12k tokens this turn"), true);
  assert.equal(hasSavingsTally("julius is a good name"), false);
});
