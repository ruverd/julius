/**
 * A repo's own `.julius/`: the learnings its sessions leave, committed with the
 * code so every teammate's agent starts from them.
 *
 *   .julius/
 *     README.md                 what the folder is, for anyone who opens it
 *     hook.cjs                  what Claude Code runs at session start (claude/init.ts)
 *     learnings/<date>-<slug>-<author>.md
 *
 * Personal learnings (about one person's setup, not the code) stay on their
 * machine in `~/.julius/repos/<repo>/notes/` (home.ts). Everything here is
 * plain markdown that reads fine without julius installed.
 *
 * Teammates' learnings arrive two ways: merged into the default branch, which
 * is just the working tree, or still on a branch they pushed. The second kind,
 * and which files each pushed branch changes, come from a cache that a
 * background `git fetch` refreshes (branches.ts), so nothing here spawns git.
 */
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

/** The folder, relative to the top of the checkout. */
export const JULIUS_DIR = ".julius";
/** Where the learnings are, relative to the top of the checkout. */
export const LEARNINGS_DIR = ".julius/learnings";

export const REPO_JULIUS_README = `# .julius

What coding sessions on this repo worked out, kept next to the code so the
next session, yours or a teammate's, starts from it instead of digging again.

- learnings/   one file per session that took real digging: what was decided,
               what was tried and ruled out, and what to watch out for, plus
               what it took to work out
- hook.cjs     what Claude Code runs at session start (\`.claude/settings.json\`).
               With julius installed it hands over to julius. Without it, it
               shows Claude these learnings and offers to set julius up.

Commit this folder and \`.claude/settings.json\` once. After that, commit new
learnings with the change they came from. Learnings are short summaries, never
transcripts, and plain markdown without julius installed. What
\`.julius/.gitignore\` lists stays on each machine.
`;

/** The README before 0.23, which pointed at the repo skill. Replaced where it's untouched. */
const OLD_READMES = [`# .julius

What coding sessions on this repo worked out, kept next to the code so the
next session, yours or a teammate's, starts from it instead of digging again.

- learnings/   one file per session that took real digging: what was decided,
               what was tried and ruled out, and what to watch out for, plus
               what it took to work out

Learnings are short summaries, never transcripts. Commit them with the change
they came from. Claude Code reads them through the julius skill
(\`.claude/skills/julius/\`); without julius installed they are plain markdown.
`];

/** `<checkout>/.julius/learnings`. */
export function learningsDir(checkout: string): string {
  return join(checkout, LEARNINGS_DIR);
}

/** The checkout has a `.julius/` (julius init made it, or a teammate committed one). */
export function hasRepoJulius(checkout: string): boolean {
  return existsSync(join(checkout, JULIUS_DIR));
}

/** Make `.julius/learnings/` and its README. Returns whether the folder is new. */
export function ensureRepoJulius(checkout: string): boolean {
  const created = !hasRepoJulius(checkout);
  mkdirSync(learningsDir(checkout), { recursive: true });
  const readme = join(checkout, JULIUS_DIR, "README.md");
  let current: string | null = null;
  try { current = readFileSync(readme, "utf8"); } catch { /* none yet */ }
  if (current === null || OLD_READMES.includes(current)) writeFileSync(readme, REPO_JULIUS_README);
  return created;
}

/** The learning files in the working tree, by name, sorted. [] without a `.julius/`. */
export function learningFiles(checkout: string): string[] {
  try {
    return readdirSync(learningsDir(checkout))
      .filter((f) => f.endsWith(".md"))
      .sort();
  } catch {
    return [];
  }
}

/** One learning file's text, or null when it can't be read. */
export function readLearningFile(checkout: string, name: string): string | null {
  try {
    return readFileSync(join(learningsDir(checkout), name), "utf8");
  } catch {
    return null;
  }
}

/** One line in `.julius/.gitignore`, added once. */
export function ignoreInJuliusDir(dir: string, entry: string): void {
  const path = join(dir, ".julius", ".gitignore");
  let text = "";
  try { text = readFileSync(path, "utf8"); } catch { /* new */ }
  if (text.split("\n").some((l) => l.trim() === entry)) return;
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${text}${text && !text.endsWith("\n") ? "\n" : ""}${entry}\n`);
}
