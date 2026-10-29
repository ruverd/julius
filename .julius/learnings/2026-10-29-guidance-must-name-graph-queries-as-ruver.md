---
title: Guidance must name graph queries as julius_call operations
author: Ruver
date: 2026-10-29
id: l-c08a3d1e
branch: fix/mcp-tool-guidance
cost: { minutes: 5, tokens: 95857 }
touches:
  - src/claude/skill-template.ts
  - src/graph/cards.ts
  - test/cards.test.ts
  - test/claude-skill-template.test.ts
  - src/mcp/instructions.ts
---

## Decided
The default compact MCP server advertises only julius_discover and julius_call. julius_find_code, julius_find_all, julius_trace_calls, julius_file_api, julius_repo_map and julius_check_freshness are operations passed to julius_call. INDEX.md text (src/graph/cards.ts writeIndex) and the skill template (src/claude/skill-template.ts) now say so. Regression tests are in test/cards.test.ts and test/claude-skill-template.test.ts.

## Tried and ruled out
The server cannot fix this. When an agent calls a tool name that is not advertised, the host rejects the call ("Tool julius-julius_find_code was not found") before the request reaches Julius.

## Watch out
src/mcp/instructions.ts (mcpInstructions) still lists these names as tools. That is correct only for the full-tools server mode. Any new agent-facing text must name the surface that the default compact server exposes. julius check reports the word "operation" in test names as a lexical false positive.
