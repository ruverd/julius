# Local MCP artifact recovery

Julius provides one offline MCP stdio tool, `restore_artifact`. It accepts an `artifactId` and returns the stored original as text while the artifact is valid. The server fixes the project ID at startup; a model cannot select a different project. It does not send model or network requests, and it does not edit any client's configuration.

Start it from an MCP client with `julius mcp recovery --project PROJECT --data-dir STORE`, or `python -m julius.mcp_recovery ARTIFACT_ROOT PROJECT_ID`. In the first form, Julius uses `STORE/artifacts`; in the second, pass that artifact root directly. Use the same project ID and store as the hook or SDK that created the artifact. Configure the client to launch this command through its local stdio transport. Treat this command and its access to the artifact directory as sensitive: a client that can invoke the tool can read valid originals for the configured project.

The server implements the MCP `2025-06-18` initialize/initialized lifecycle, `ping`, `tools/list`, and `tools/call` over newline-delimited UTF-8 JSON-RPC. It advertises only the `tools` capability and one tool. Unsupported methods return JSON-RPC errors. Missing, expired, damaged, cross-project, or unsafe artifacts return a tool error without exposing stored content. Input messages are limited to 64 KiB; artifacts retain the store's 1 MiB limit.

Protocol references: [lifecycle](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle), [tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools), [stdio transport](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports).
