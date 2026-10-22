/** What `julius check` reads: the branch's changes, without the wiring `julius init` wrote. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { branchDiff } from "../src/cloud/diff.js";
import { tmpRepo } from "./helpers.js";

function git(d: string, args: string[]) {
  spawnSync("git", ["-c", "commit.gpgsign=false", "-c", "user.name=T", "-c", "user.email=t@x", ...args], { cwd: d });
}

test("julius check leaves out the files julius init writes", () => {
  const d = tmpRepo("check-diff");
  writeFileSync(join(d, "client.go"), "package x\n\nconst defaultRetryMax = 4\n");
  git(d, ["init", "-q", "-b", "main"]);
  git(d, ["add", "-A"]);
  git(d, ["commit", "-qm", "init"]);
  // The wiring, committed on main but never pushed, then a branch with a real change.
  mkdirSync(join(d, ".claude", "skills", "julius"), { recursive: true });
  writeFileSync(join(d, ".claude", "skills", "julius", "SKILL.md"), "# julius\n");
  writeFileSync(join(d, ".mcp.json"), "{}\n");
  writeFileSync(join(d, "client.go"), "package x\n\nconst defaultRetryMax = 10\n");
  git(d, ["add", "-A"]); // staged, so plain git diff would show every one of them
  const r = branchDiff(d, "HEAD");
  assert.deepEqual(r?.files, ["client.go"]);
  assert.doesNotMatch(r!.diff, /SKILL\.md|mcp\.json/);
  assert.match(r!.diff, /defaultRetryMax = 10/);
});
