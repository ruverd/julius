# Installation and migration

Install the public package with `npm install -g @ruverd/julius`, then run
`julius install`. The [README](../README.md#install) also documents installation
from the default `main` branch through a local tarball. The transactional MCP
installer uses the installed package; it never launches npx or asks a registry
for the server.

## Updating

Run `npm install -g @ruverd/julius@latest` and check `julius --version`. Restart
or reconnect the client's MCP session so its long-running server loads the new
code. If the Node executable or package path changes, run `julius install` again.
Repository graphs refresh locally on demand; shared `.julius/learnings` survive
the package update. Pin an earlier version with
`npm install -g @ruverd/julius@<version>` when a rollback is needed.

Prereleases use the `next` dist-tag: `npm install -g @ruverd/julius@next`.
Maintainers follow [the release procedure](releasing.md).

`julius install` detects configuration directories in the selected home. The
supported global targets are:

| Host | Configuration | Managed entry |
| --- | --- | --- |
| Claude Code | `~/.claude.json` | `mcpServers.julius` |
| Cursor | `~/.cursor/mcp.json` | `mcpServers.julius` |
| Codex | `~/.codex/config.toml` | `[mcp_servers.julius]` |

Explicit selection: `julius install --hosts claude,cursor,codex,grok`. The selected
home must exist; `--home <path>` supports isolated testing. All paths may contain
spaces. Installed paths are argv elements, never shell-interpolated commands.
The host must launch MCP in the working repository; Julius does not infer a
repository from editor UI state. The stdio second-repository test proves cwd
resolution independently of the installation checkout.

## Ownership and rollback

Before writing, setup validates every target and prepares snapshots under
`~/.julius/install`. It uses an exclusive transaction lock, rechecks each target
before replacing it, and journals prior and proposed bytes. A caught failure
restores exact bytes only when the current file still matches the transaction's
write. If a concurrent writer changed it, setup leaves that file and the journal
intact and reports a conflict. A process crash can also leave the journal/lock;
inspect those snapshots and reconcile manually before removing recovery files
and retrying. There is no automatic crash recovery that overwrites newer edits.
Configuration editors do not share Julius's lock; stop them during setup to
avoid the remaining filesystem check/rename race.

`julius uninstall --global` restores prior managed entries. Unchanged files
return to their original bytes (or are removed if newly created). With unrelated
edits, JSON settings are preserved semantically and reformatted; foreign TOML
text is preserved. Changed managed entries cause a conflict before any target is
changed. Reinstall also preserves foreign changes for the eventual uninstall.
Migration copies remain after uninstall; deleting user learnings is not part of
undoing MCP setup. Snapshots may contain private configuration; files are written
with owner-only permissions.

Codex and Grok input is validated with smol-toml. The text editor supports canonical
single-line table headers and rejects multiline TOML or ambiguous quoted,
dotted, nested or duplicate owned tables. This conservative limitation avoids
editing text whose ownership cannot be established; use manual MCP registration
for such a configuration. Replaced values and foreign settings are not inferred
from a client account or sent anywhere.

## Explicit Trail migration

```sh
julius install --migrate-trail '/path/to/existing repo' --dry-run
julius install --migrate-trail '/path/to/existing repo'
```

This copies `.trail/learnings` recursively to `.julius/learnings`, preserving
original bytes. Equal copies are skipped, conflicting destinations fail before
writes, and symlinks/special files are refused. The old directory is never
changed. Graph caches are rebuilt locally instead of copied.

Only exact known Trail MCP launch entries (`trail mcp` or
`npx -y @trailhq/trail-code mcp`) qualify for removal.
Additional arguments/settings or merely similar names do not qualify. Setup
removes verified entries in selected global host configs and the explicitly
named repository's `.mcp.json` and `.cursor/mcp.json`. Those removals participate
in rollback and uninstall restoration. Other legacy hooks, skills or custom
launchers are outside this migration; review them separately if still active.

The inherited `julius init` remains available for repository/team hooks and
other host adapters. Its best-effort cleanup is different from this ownership
transaction. `julius uninstall` without `--global` remains the inherited inverse
of init (preview by default, `-y` to apply). Avoid mixing both setup methods in
one host without reviewing their configurations.

## Normal conversation after setup

Once Julius is registered and the host loads its MCP server, ask normal coding
questions. The agent discovers and runs investigations itself; no Julius command
or slash command is needed during coding. New repositories are indexed locally
on demand. A session may need restarting after installation or an upgrade.
Host tool permissions still apply, and model tool selection cannot be guaranteed.
This integration targets coding clients with local MCP support, not ordinary web
chats. Grok uses the native xAI CLI TOML format documented in its
[MCP guide](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/07-mcp-servers.md).

See [investigations](investigations.md) for current behavior and limitations.
