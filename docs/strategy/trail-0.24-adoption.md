# Trail 0.24 against Julius

Date: 2026-10-22. The Adopt rows and the Adapt rows are in the working tree. The Leave rows are not.

Julius is pinned at Trail-Code `b1211ef` (release 0.23.1). The installed package `@trailhq/trail-code@0.24.0` matches GitHub `HEAD` `b155680` (2026-10-22). That tip is 31 commits ahead of the pin. GitHub has no `v0.24.0` tag, and the published changelog still ends at 0.23.1. The list below is those 31 commits, not the changelog.

Copying the package over Julius would drop the Julius names, the economy store, and selective delivery. Each row is adopt, adapt, or leave.

## Adopt

Local fixes. No new service, no telemetry, no brand restore.

| Commit | What changed | Why |
| --- | --- | --- |
| `7326bdac0` | Update check honors `DO_NOT_TRACK` | Same rule Julius already uses for telemetry. The upkeep poll should follow it. |
| `187d5ea8e` | Do not append `/graft/` when git already ignores that directory | Stops a repeated gitignore edit. Keep the Julius path (`.julius` / worktrees), not the graft path. |
| `acbec1012` | Skip writing a graph card that did not change | Less disk churn on rebuild. |
| `bdf8fd643` | Hook skips retrieval of background task notifications | Stops a session from pulling a notification that is not the user's turn. |
| `e447ee3b9` | `build` remembers `--no-gitignore` | A saved option should survive the next build. |

## Adapt, then adopt

These are the learning changes. Julius already has `julius note`, `julius check`, and `.julius/learnings/` from the 0.23.1 pin. The new commits extend that. Port the behavior under Julius names. Do not copy `.trail` paths, `trail` commands, or the install-trail prompt.

| Commit | What changed | What to keep |
| --- | --- | --- |
| `53ba78085` | Learning fields: id, kind, scope, status, `replaces` | A newer learning can retire an older one. `julius check` and recall read only live notes. Old files without the fields keep working. |
| `94a9b7924` | Ask for a learning on a real signal, and refuse a weak one | Signals: a check that failed then passed, a correction, an undone edit, a picked option, a commit, a shell rewrite of a file, or one turn that saved 30k tokens of reading. Cap: one ask per signal, three a session. `note` refuses a team learning with no code, no reason, a setup note, a status note, or a repeat. `--replaces` points at the old id. |
| `134342e6e` | Read commands that ran from the session transcript | Julius already reads a transcript for note cost. Use the same read to see a shell edit. The command-risk scan (force-push, and the skill compiler's walls) stays out until the skills row is accepted. |

## Leave

| Commit | What changed | Why it stays out |
| --- | --- | --- |
| `b1556804e` | Skills store, compile, save, validate (95 files) | New product: takeaways in `~/.trail`, fold into `.claude/skills`, `trail learn` / `trail skills publish`. Local, but a separate project. It sits on the transcript and risk work above. |
| `5bf8dd2a9` | `init` offers what teammates' Claude does not know | The useful half is already in 0.23.1. The shipped copy also points people at installing trail. |
| `c046c64bf` | Quieter npm install; tick chosen rows in `init` | Init polish. Take it only while touching init. |
| `89248a9de` | Vendor `tree-sitter-swift` so a global install warns less | Packaging. Take it with the next install work, not as behavior. |
| `f5fcc76cb` | Gleam graph support | A language grammar. Add it when a repo needs Gleam. |
| `ff56c78ec`, `c07101c00`, `25b64523c`, `afdaea9f6`, `4c41fe47a` | Deep-index speed and LLM response repairs | The deep pass calls a provider. Julius keeps that off unless the user configures it. Port a repair only while fixing that opt-in path. |
| `87d954373`, `47da7ea51` | Windows console and language-server launch | No Windows target in this session. |
| `22aa846bc` | Viewer: a pan no longer deselects | Unrelated UI. |
| `11893f920`, `171ee65e7`, `f1f0e840b`, `a27942b44`, `db0707baa`, `590c9efe1`, `e48c4b679`, `4ea6b226d`, `86e6c29f5`, `a7312d3e0` | Dependency and CI bumps | Update the lockfile when a dependency is already being changed. Do not take the batch for its own sake. |

## Already in Julius, not part of this delta

Selective delivery (`line` + `text`, 160 characters, handle kept) is a Julius change. Trail 0.24's `grep` already returned that hit shape. The learning store was not copied from 0.24.

## Not a source of savings

Provider token use on a real project is still null. Trail `grep` is cheaper for a fresh code lookup. Julius spends less only when a stored result would otherwise be sent again.
