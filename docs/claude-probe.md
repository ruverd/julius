# Local Claude integration probe

`julius` can probe its own Claude hook and recovery MCP server without launching Claude Code. The probe uses the installed Python interpreter to run both Julius commands in subprocesses with bounded timeouts. It creates one temporary artifact from a synthetic Bash result, sends an MCP initialize request, lists tools, and restores that exact result through `restore_artifact`. The temporary data directory is removed afterward.

The returned `scope` is always `local_protocol`. A successful result establishes that these Julius subprocesses completed this local roundtrip. It does not establish that a live Claude Code version loads the temporary settings, connects to this server, exposes the tool to the model, honors the hook response, or grants a permission. The probe neither reads Claude credentials nor sends a model request. A live client check requires a separate, explicit session.
