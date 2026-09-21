# Opt-in project integration management

Codex project hooks can be managed with
`julius setup --integration codex --project-root ./project`. The project's
`.codex` directory must already exist. Preview prints a `hooksDiff` and
`planHash`; apply requires `--apply-plan '<planHash>'`. The manager adds one
`UserPromptSubmit` command in `.codex/hooks.json`, preserves other hook groups,
and backs up the exact original bytes and mode outside the project. Use
`julius integrations remove codex --project-root ./project` to restore it.
Removal refuses drift. The hook returns `{}` by default and cannot rewrite
prompt/tool content or demonstrate savings. Codex's [project trust and hook
review](https://developers.openai.com/codex/hooks) remain mandatory; Julius
does not bypass them. The setup command itself does not call a model.

## Claude

`ClaudeIntegrationManager(project_root, state_root)` manages only `project_root/.claude/settings.json` and `project_root/.mcp.json`. The project `.claude` directory must already exist, and the separate state directory must satisfy `ManagedConfig`'s private-directory checks. No global Claude configuration is touched.

Call `preview(hook_command=..., mcp_command=..., mcp_args=...)` to receive two `ConfigPlan` objects with unified diffs and complete desired bytes. Preview does not write project files. Review both diffs, then call `apply(plan)` in response to an explicit user action. Apply checks both files for drift, writes private backups and manifests through `ManagedConfig`, and rolls back the hook when MCP application fails. Repeating the same apply is a no-op. `remove()` checks that both managed files still match their recorded hashes, then restores exact prior bytes and modes. Repeating removal is a no-op. If either file changed, removal refuses both files; resolve drift manually.

The hook command is caller supplied. A command containing `--recovery-available` is rejected unless `recovery_verified=True` is passed after verifying that Claude can access the recovery MCP tool for the same project and artifact store. Passing this flag is an operator attestation, not a verification performed by Julius. Without it, the installed hook passes through tool output. This manager does not prove live Claude compatibility, install a client, or trigger a model request. Tests use temporary files and fixture JSON.

Claude Code documents project hooks in [settings](https://code.claude.com/docs/en/hooks) and project MCP servers in [`.mcp.json`](https://code.claude.com/docs/en/mcp#project-scope). Project MCP entries may load without an interactive prompt in noninteractive sessions, so review the generated commands before applying.
