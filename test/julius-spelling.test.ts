/**
 * Under julius, what the agent reads names commands it can run. A julius-only
 * install has no `julius` binary, so a hint that says `julius ask` costs a failed
 * tool call. Under julius the same text is unchanged.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { BRAND_ENV } from "../src/brand.js";
import { weakMatchNudge } from "../src/claude/format.js";
import { hasSavingsTally } from "../src/claude/tally.js";
import type { SessionState } from "../src/claude/state.js";
import { savingsTurnNudge } from "../src/context/savings.js";
import { zeroHitNote } from "../src/search/grep-cli.js";
import type { GrepResult } from "../src/search/grep.js";

/** A julius command a julius-only machine can't run. */
const JULIUS_COMMAND = /\bjulius (ask|build|grep|callers|skeleton|map|blast|telemetry)\b|\[julius\]|julius saved/;

function under<T>(name: "julius" | "julius", fn: () => T): T {
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
    savingsTurnNudge(1200),
    zeroHitNote(grepMiss),
  ]);
  for (const line of lines) {
    assert.match(line, JULIUS_COMMAND, line);
    assert.match(line, /julius/, line);
  }
});

test("under julius the same hints keep julius's words", () => {
  assert.match(under("julius", () => weakMatchNudge({ nudges: 0 } as SessionState, 0.1)!), /^\[julius\] .*`julius ask "<your task>" --source`/);
  assert.match(under("julius", () => savingsTurnNudge(1200)), /🌱 julius saved/);
});

test("a julius tally counts as telling the user what was saved", () => {
  assert.equal(hasSavingsTally("🌱 julius saved ~12k tokens (~$0.04) this turn, 3 calls"), true);
  assert.equal(hasSavingsTally("🌱 julius saved ~12k tokens this turn"), true);
  assert.equal(hasSavingsTally("julius is a good name"), false);
});
