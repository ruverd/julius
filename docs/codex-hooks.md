# Codex context hook adapter

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
adapter. A caller must supply trusted, locally prepared text. There is no claim of
verified live client compatibility; these are fixture tests of the documented
wire shapes.

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
