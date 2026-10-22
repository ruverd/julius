/**
 * What `julius init` shares and what it keeps personal. Shared, committed once:
 * `.julius/hook.cjs` and one SessionStart entry in `.claude/settings.json`.
 * Personal, never in git: the status line, allowlist and (under --no-global)
 * the other hooks in `.claude/settings.local.json`, and the skill in ~/.claude.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { join } from "node:path";
import { tmpRepo } from "./helpers.js";
import { runInit, keepOutOfGit } from "../src/claude/init.js";
import { mergeJuliusLocal, mergeJuliusShared } from "../src/claude/settings-merge.js";
import { globalCopyCovers } from "../src/claude/hook-layers.js";
import { setupUncommitted } from "../src/claude/hooks.js";
import { setupCommitLine } from "../src/notes/notes.js";
import { ensureRepoJulius, REPO_JULIUS_README } from "../src/notes/repo-julius.js";
import { hooksShim } from "../src/claude/shim-template.js";
import { CI_ENV_VARS } from "../src/telemetry/gate.js";

const git = (cwd: string, ...args: string[]) =>
  spawnSync("git", ["-c", "commit.gpgsign=false", "-c", "user.name=T", "-c", "user.email=t@t.test", ...args], { cwd, encoding: "utf8" });

function gitRepo(tag: string): string {
  const d = tmpRepo(tag);
  git(d, "init", "-q");
  return d;
}

test("the shared settings get one SessionStart entry, and lose what an older init put there", () => {
  const older = {
    statusLine: { type: "command", command: 'node "${CLAUDE_PROJECT_DIR:-.}/.claude/helpers/julius-statusline.cjs"' },
    hooks: {
      SessionStart: [
        { hooks: [{ type: "command", command: "./scripts/fetch-secrets.sh" }] },
        { hooks: [{ type: "command", command: 'node "${CLAUDE_PROJECT_DIR:-.}/.claude/helpers/julius-hooks.cjs" session-start' }] },
      ],
      UserPromptSubmit: [{ hooks: [{ type: "command", command: 'node "${CLAUDE_PROJECT_DIR:-.}/.claude/helpers/julius-hooks.cjs" prompt' }] }],
    },
    permissions: { allow: ["Bash(julius:*)", "Bash(make:*)"] },
    footerLinksRegexes: ["julius/[\\w./-]+\\.md"],
  };
  const shared = mergeJuliusShared(older);
  assert.equal(shared.statusLine, undefined);
  assert.deepEqual(Object.keys(shared.hooks), ["SessionStart"]);
  assert.equal(shared.hooks.SessionStart[0].hooks[0].command, "./scripts/fetch-secrets.sh", "the team's own hook stays, first");
  assert.equal(shared.hooks.SessionStart[1].hooks[0].command, 'node "${CLAUDE_PROJECT_DIR:-.}/.julius/hook.cjs" session-start');
  assert.deepEqual(shared.permissions, { allow: ["Bash(make:*)"] });
  assert.equal(shared.footerLinksRegexes, undefined);
  assert.deepEqual(mergeJuliusShared(shared), shared, "a second run changes nothing");
});

test("the personal settings carry the hooks only when ~/.claude doesn't, and never session start", () => {
  const withHooks = mergeJuliusLocal({}, { hooks: true }).merged;
  assert.match(withHooks.statusLine.command, /\.julius\/statusline\.cjs/);
  assert.equal(withHooks.hooks.SessionStart, undefined, "the shared file runs it, once");
  for (const e of ["UserPromptSubmit", "Stop", "SessionEnd", "PostToolUse"]) assert.ok(withHooks.hooks[e], e);
  assert.deepEqual(mergeJuliusLocal(withHooks, { hooks: true }).merged, withHooks, "a second run changes nothing");

  const withoutHooks = mergeJuliusLocal(withHooks, { hooks: false }).merged;
  assert.equal(withoutHooks.hooks, undefined, "~/.claude carries them now");
  assert.ok(withoutHooks.permissions.allow.includes("Bash(julius:*)"));

  const mine = { statusLine: { type: "command", command: "my-line" } };
  const kept = mergeJuliusLocal(mine);
  assert.equal(kept.merged.statusLine.command, "my-line");
  assert.equal(kept.warnings.length, 1);
});

test("julius init leaves git status with only the shared files, and writes the skill to ~/.claude", () => {
  const d = gitRepo("layout");
  const home = tmpRepo("layout-home");
  writeFileSync(join(d, ".gitignore"), "node_modules/\n");
  git(d, "add", "-A");
  git(d, "commit", "-qm", "base");

  runInit(d, { build: false, home, brand: "julius" });
  const status = git(d, "status", "--porcelain", "--untracked-files=all").stdout.trim().split("\n").map((l) => l.slice(3)).sort();
  assert.deepEqual(status, [".claude/settings.json", ".julius/.gitignore", ".julius/hook.cjs"]);
  assert.equal(readFileSync(join(d, ".gitignore"), "utf8"), "node_modules/\n", ".gitignore untouched");
  assert.equal(existsSync(join(d, ".mcp.json")), false, "no MCP server for Claude Code");
  assert.ok(existsSync(join(home, ".claude", "skills", "julius", "SKILL.md")));
  assert.equal(existsSync(join(d, ".claude", "skills")), false);
  assert.equal(readFileSync(join(d, ".julius", "hook.cjs"), "utf8"), hooksShim());
});

test("julius init with telemetry on leaves no julius/ folder behind", () => {
  // init's first event comes from the past-session read, before anything else
  // is written: the repo id it mints must land in .julius/cache/, which
  // .julius/.gitignore keeps out of git, not in a julius/ that nothing ignores.
  const d = gitRepo("init-telemetry");
  const home = tmpRepo("init-telemetry-home");
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    HOME: home,
    USERPROFILE: home,
    JULIUS_HOME: join(home, ".julius"),
    JULIUS_POSTHOG_KEY: "phc_test_key",
    JULIUS_POSTHOG_HOST: "https://127.0.0.1:9",
  };
  for (const k of [...CI_ENV_VARS, "DO_NOT_TRACK", "JULIUS_NO_FETCH", "CLAUDECODE", "JULIUS_INVOKED_AS"]) delete env[k];
  const r = spawnSync(process.execPath, ["--import", "tsx", join(process.cwd(), "src", "bin", "julius.ts"), "init", d, "--agents", "claude", "--no-build", "--no-global"], { encoding: "utf8", env });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(existsSync(join(d, "julius")), false, "no old graph folder");
  assert.ok(existsSync(join(d, ".julius", "cache", ".cache", "telemetry-repo-id.json")), "the event was queued, with its repo id under .julius/cache/");
});

test("init over a repo set up the old way moves it: old shims, repo skill and julius's server go", () => {
  const d = gitRepo("old-layout");
  const home = tmpRepo("old-layout-home");
  mkdirSync(join(d, ".claude", "helpers"), { recursive: true });
  mkdirSync(join(d, ".claude", "skills", "julius"), { recursive: true });
  writeFileSync(join(d, ".claude", "helpers", "julius-hooks.cjs"), "old");
  writeFileSync(join(d, ".claude", "helpers", "julius-statusline.cjs"), "old");
  writeFileSync(join(d, ".claude", "skills", "julius", "SKILL.md"), "old");
  writeFileSync(join(d, ".mcp.json"), JSON.stringify({ mcpServers: { julius: { command: "julius", args: ["mcp"] }, db: { command: "pg" } } }));

  runInit(d, { build: false, home, global: false });
  assert.equal(existsSync(join(d, ".claude", "helpers")), false);
  assert.equal(existsSync(join(d, ".claude", "skills")), false);
  assert.deepEqual(JSON.parse(readFileSync(join(d, ".mcp.json"), "utf8")), { mcpServers: { db: { command: "pg" } } }, "the team's other servers stay");
  assert.ok(existsSync(join(d, ".julius", "hook.cjs")));
});

test("a personal file goes in .git/info/exclude only when nothing ignores it yet", (t) => {
  // This machine's own git config may ignore it already (Claude Code adds it to the global excludes file).
  const saved = { global: process.env.GIT_CONFIG_GLOBAL, xdg: process.env.XDG_CONFIG_HOME };
  const empty = tmpRepo("exclude-gitconfig");
  writeFileSync(join(empty, "config"), "");
  process.env.GIT_CONFIG_GLOBAL = join(empty, "config");
  process.env.XDG_CONFIG_HOME = empty;
  t.after(() => {
    for (const [k, v] of [["GIT_CONFIG_GLOBAL", saved.global], ["XDG_CONFIG_HOME", saved.xdg]] as const)
      if (v === undefined) delete process.env[k]; else process.env[k] = v;
  });
  const d = gitRepo("exclude");
  keepOutOfGit(d, join(".claude", "settings.local.json"));
  const exclude = readFileSync(join(d, ".git", "info", "exclude"), "utf8");
  assert.match(exclude, /^\/\.claude\/settings\.local\.json$/m);
  keepOutOfGit(d, join(".claude", "settings.local.json"));
  assert.equal(readFileSync(join(d, ".git", "info", "exclude"), "utf8"), exclude, "once");

  const ignored = gitRepo("exclude-ignored");
  writeFileSync(join(ignored, ".gitignore"), ".claude/settings.local.json\n");
  const before = readFileSync(join(ignored, ".git", "info", "exclude"), "utf8");
  keepOutOfGit(ignored, join(".claude", "settings.local.json"));
  assert.equal(readFileSync(join(ignored, ".git", "info", "exclude"), "utf8"), before, "already ignored: nothing added");

  keepOutOfGit(tmpRepo("not-git"), join(".claude", "settings.local.json")); // no checkout: no throw
});

test("the shared hook stands down when ~/.claude answers the event, like the old repo copy", () => {
  const home = tmpRepo("layers-home");
  const helpers = join(home, ".claude", "helpers");
  mkdirSync(helpers, { recursive: true });
  const globalShim = join(helpers, "julius-hooks.cjs");
  writeFileSync(globalShim, hooksShim());
  const cmd = `node "${globalShim.replace(/\\/g, "/")}" session-start`;
  writeFileSync(join(home, ".claude", "settings.json"), JSON.stringify({ hooks: { SessionStart: [{ hooks: [{ type: "command", command: cmd }] }] } }));
  assert.equal(globalCopyCovers("session-start", join(tmpRepo("layers-repo"), ".julius", "hook.cjs"), home), true);
  assert.equal(globalCopyCovers("prompt", join(tmpRepo("layers-repo2"), ".julius", "hook.cjs"), home), false);
});

test("the first reply asks for the shared setup until it's committed", () => {
  const d = gitRepo("setup-nudge");
  const home = tmpRepo("setup-nudge-home");
  writeFileSync(join(d, "README.md"), "x\n");
  git(d, "add", "-A");
  git(d, "commit", "-qm", "base");
  assert.equal(setupUncommitted(d), false, "no julius here");

  runInit(d, { build: false, home, global: false, brand: "julius" });
  assert.equal(setupUncommitted(d), true, "the hook isn't tracked");
  git(d, "add", ".julius/hook.cjs");
  git(d, "commit", "-qm", "hook only");
  assert.equal(setupUncommitted(d), true, "HEAD's settings don't run it");
  git(d, "add", "-A");
  git(d, "commit", "-qm", "settings");
  assert.equal(setupUncommitted(d), false);

  assert.equal(
    setupCommitLine(["Anay Shah", "Rushil"]),
    "🌱 Anay Shah and Rushil work in this repo. Commit .julius/ and .claude/settings.json once, and their Claude starts from your learnings, even before they install julius",
  );
});

test("an untouched old README is brought up to date, an edited one is left alone", () => {
  const d = tmpRepo("readme");
  mkdirSync(join(d, ".julius"), { recursive: true });
  const old = "# .julius\n\nWhat coding sessions on this repo worked out, kept next to the code so the\nnext session, yours or a teammate's, starts from it instead of digging again.\n\n- learnings/   one file per session that took real digging: what was decided,\n               what was tried and ruled out, and what to watch out for, plus\n               what it took to work out\n\nLearnings are short summaries, never transcripts. Commit them with the change\nthey came from. Claude Code reads them through the julius skill\n(`.claude/skills/julius/`); without julius installed they are plain markdown.\n";
  writeFileSync(join(d, ".julius", "README.md"), old);
  ensureRepoJulius(d);
  assert.equal(readFileSync(join(d, ".julius", "README.md"), "utf8"), REPO_JULIUS_README);

  writeFileSync(join(d, ".julius", "README.md"), "# ours\n");
  ensureRepoJulius(d);
  assert.equal(readFileSync(join(d, ".julius", "README.md"), "utf8"), "# ours\n");
});
