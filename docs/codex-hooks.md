# Codex context hook adapter

`julius hook codex-user-prompt-submit` (or `python -m julius.codex_hook_command`) is an executable `UserPromptSubmit` hook
endpoint. It consumes one JSON event from stdin and writes one JSON response to
stdout. By default the response is `{}`, so the hook observes the event without
changing Codex's behavior. To add an operator-reviewed local note, run
`julius hook codex-user-prompt-submit --trusted-context-file /absolute/path/to/reviewed.txt`.
The file is explicitly selected by the operator; do not point it at a prompt,
transcript, tool output, retrieved document, or other untrusted text. The
endpoint reads at most 65,536 input bytes and 32,000 note bytes, returns `{}`
for malformed or oversized input, and writes no logs, settings, or credentials.
It does not install a hook or call a model. Keep the command in a trusted Codex
hook configuration if you choose to enable it.

`julius.codex_hooks.additive_context_output(event, context, trusted_context=True)` is a pure adapter
for the documented `SessionStart` and `UserPromptSubmit` Codex hook events. It
returns `hookSpecificOutput.additionalContext` with a matching `hookEventName`.
That text is added as developer context; it does **not** replace or optimize
the user's prompt, tool input, or tool output. The adapter returns `{}` for
unsupported events, missing required event fields, or empty context. It limits
context to 8,000 characters to avoid unbounded hook output. The default
`trusted_context=False` returns `{}` even when context is supplied. Callers
must explicitly mark context trusted after constructing it from reviewed,
trusted local instructions or metadata. Never pass raw user prompts, tool
results, transcripts, retrieved documents, or other untrusted source content:
the hook output is promoted to developer context.

Julius does not install or enable a hook, edit Codex settings, read a
transcript, send a model request, or perform network access through this
adapter. A caller must supply trusted, locally prepared text. On September 21,
2026, one bounded synthetic Codex CLI 0.154.0 turn used the actual `julius hook
codex-user-prompt-submit` command with an ephemeral inline hook configuration
and a reviewed temporary note. The final answer matched the note's marker;
Codex reported 21,388 input and 24 output tokens. This proves additive-context
acceptance for that exact command and version, not tool-output replacement,
traffic coverage, or savings. The separate [temporary hook probe](codex-hook-probe.md)
also passed on that version.

`PreToolUse` and `PermissionRequest` have distinct control contracts. This
adapter never returns `permissionDecision`, `updatedInput`, `decision`,
`continue`, or `stopReason`, so Codex retains its normal tool and approval
behavior. In particular, `UserPromptSubmit` supports added context and prompt
blocking, but the current documented contract has no prompt replacement
field. Hook coverage is also incomplete for some specialized tool paths.

Sources checked September 21, 2026:

- [Codex hooks reference](https://developers.openai.com/codex/hooks), especially
  Common input/output fields, SessionStart, UserPromptSubmit, PreToolUse,
  PermissionRequest, and Tool coverage.
- [Codex advanced configuration](https://developers.openai.com/codex/config-advanced)
  for hook discovery and project trust behavior.
