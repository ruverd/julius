/**
 * Persisted local build configuration.
 *
 * Explicit directory and submodule choices must survive later no-flag builds
 * and the hooks/refresh path, which never sees CLI flags. These tests pin the
 * round-trip and merge contracts independently of the CLI wiring.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { ensureRepoJulius, ignoreInJuliusDir } from "../src/notes/repo-julius.js";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  buildConfigPath,
  cacheDir,
  patchBuildConfig,
  readBuildConfig,
  readFollowSubmodules,
  readIncludeDirs,
  resolveContextDir,
  writeBuildConfig,
} from "../src/util/state.js";

function fresh(): string {
  return mkdtempSync(join(tmpdir(), "julius-buildconfig-"));
}

test("readBuildConfig returns null when nothing was ever persisted", () => {
  const d = fresh();
  assert.equal(readBuildConfig(d), null);
  assert.equal(readIncludeDirs(d), undefined, "no persisted config -> today's default (no includes)");
  assert.equal(readFollowSubmodules(d), false, "no persisted config -> historical submodule boundary");
});

test("writeBuildConfig + readBuildConfig round-trip includeDirs", () => {
  const d = fresh();
  writeBuildConfig(d, { includeDirs: ["build", "vendor"] });
  assert.deepEqual(readBuildConfig(d), { includeDirs: ["build", "vendor"] });
  assert.equal(buildConfigPath(d), join(d, ".julius", "config.json"));
  assert.equal(existsSync(join(d, ".julius", "cache", ".cache", "config.json")), false);
  assert.match(readFileSync(join(d, ".julius", ".gitignore"), "utf8"), /^config\.json$/m);
});

test("readIncludeDirs turns a persisted list into a Set; an empty persisted list reads as undefined (default behavior)", () => {
  const d = fresh();
  writeBuildConfig(d, { includeDirs: ["build"] });
  assert.deepEqual(readIncludeDirs(d), new Set(["build"]));

  writeBuildConfig(d, { includeDirs: [] });
  assert.equal(readIncludeDirs(d), undefined, "an empty list must read exactly like no list at all");
});

test("followSubmodules round-trips true and explicit false", () => {
  const d = fresh();
  writeBuildConfig(d, { followSubmodules: true });
  assert.equal(readFollowSubmodules(d), true);

  writeBuildConfig(d, { followSubmodules: false });
  assert.deepEqual(readBuildConfig(d), { followSubmodules: false });
  assert.equal(readFollowSubmodules(d), false);
});

test("patchBuildConfig preserves unrelated persisted build choices", () => {
  const d = fresh();
  writeBuildConfig(d, { includeDirs: ["build"] });
  patchBuildConfig(d, { followSubmodules: true });
  assert.deepEqual(readBuildConfig(d), {
    includeDirs: ["build"],
    followSubmodules: true,
  });

  patchBuildConfig(d, { includeDirs: ["vendor"] });
  assert.deepEqual(readBuildConfig(d), {
    includeDirs: ["vendor"],
    followSubmodules: true,
  });

  patchBuildConfig(d, { followSubmodules: false });
  assert.deepEqual(readBuildConfig(d), {
    includeDirs: ["vendor"],
    followSubmodules: false,
  });
});

// ── resolveContextDir / JULIUS_DIR ──────────────────────────────────────────
//
// Everything in this module keyed only by a project dir (stats cache, sync
// lock, session state, the upkeep stamp) resolves its `julius/` subpath
// through resolveContextDir, so hooks/sync-run/statusline honor JULIUS_DIR
// the same way a direct `--dir` CLI call already does via contextDirFor.

function withJuliusDir<T>(value: string | undefined, fn: () => T): T {
  const prev = process.env.JULIUS_DIR;
  if (value === undefined) delete process.env.JULIUS_DIR; else process.env.JULIUS_DIR = value;
  try { return fn(); }
  finally { if (prev === undefined) delete process.env.JULIUS_DIR; else process.env.JULIUS_DIR = prev; }
}

test("resolveContextDir defaults to <projectDir>/julius when JULIUS_DIR is unset", () => {
  const d = fresh();
  withJuliusDir(undefined, () => {
    assert.equal(resolveContextDir(d), join(d, ".julius", "cache"));
    assert.equal(cacheDir(d), join(d, ".julius", "cache", ".cache"));
  });
});

test("resolveContextDir resolves a relative JULIUS_DIR against projectDir", () => {
  const d = fresh();
  withJuliusDir(".repo-docs/julius", () => {
    assert.equal(resolveContextDir(d), join(d, ".repo-docs", "julius"));
    assert.equal(cacheDir(d), join(d, ".repo-docs", "julius", ".cache"));
  });
});

test("resolveContextDir takes an absolute JULIUS_DIR verbatim", () => {
  const d = fresh();
  const abs = join(tmpdir(), "julius-context-elsewhere");
  withJuliusDir(abs, () => {
    assert.equal(resolveContextDir(d), abs);
    assert.equal(cacheDir(d), join(abs, ".cache"));
  });
});


test("persisting build settings ignores local state without hiding shared Julius files", () => {
  const repo = fresh();
  const git = (...args: string[]) => spawnSync("git", args, { cwd: repo, encoding: "utf8" });
  try {
    assert.equal(git("init", "-q").status, 0);
    writeFileSync(join(repo, ".gitignore"), "vendor/\n");
    ensureRepoJulius(repo);
    writeFileSync(join(repo, ".julius", "learnings", "shared.md"), "Keep shared learnings in Git.\n");
    writeFileSync(join(repo, ".julius", "hook.cjs"), "// shared session bootstrap\n");
    mkdirSync(join(repo, ".julius", "cache"));
    writeFileSync(join(repo, ".julius", "cache", "graph.json"), "{}");
    writeFileSync(join(repo, ".julius", "statusline.cjs"), "// personal statusline\n");
    ignoreInJuliusDir(repo, "cache/");
    ignoreInJuliusDir(repo, "statusline.cjs");

    writeBuildConfig(repo, { includeDirs: ["vendor"] });
    patchBuildConfig(repo, { followSubmodules: true, followNestedRepos: false });

    const shared = [".julius/learnings/shared.md", ".julius/README.md", ".julius/hook.cjs"];
    for (const path of shared) assert.equal(git("check-ignore", "--", path).status, 1, `${path} must remain Git-visible`);
    for (const path of [".julius/config.json", ".julius/cache/graph.json", ".julius/statusline.cjs"]) {
      assert.equal(git("check-ignore", "--", path).status, 0, `${path} must remain local`);
    }
    assert.equal(readFileSync(join(repo, ".gitignore"), "utf8"), "vendor/\n", "root rules are untouched");
    const ignored = readFileSync(join(repo, ".julius", ".gitignore"), "utf8");
    assert.equal(ignored.split("\n").filter((line) => line === "config.json").length, 1, "repeated configuration writes are idempotent");
    const added = git("add", "--", ...shared);
    assert.equal(added.status, 0, added.stderr);
    assert.deepEqual(git("ls-files").stdout.trim().split("\n").sort(), shared.sort());
    assert.deepEqual(readBuildConfig(repo), { includeDirs: ["vendor"], followSubmodules: true, followNestedRepos: false });
  } finally { rmSync(repo, { recursive: true, force: true }); }
});
