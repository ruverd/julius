/**
 * The julius MCP tool names, kept in a zero-import module so both the MCP server
 * (which also pulls in the whole engine) and the session-scoring hooks (which must
 * stay cheap and engine-free) can share one list. Adding a dependency here would
 * drag it into every hook invocation, so this file imports nothing.
 */

/** The tools julius advertises today, as their canonical names. */
export const JULIUS_MCP_TOOL_CANONICAL = [
  'julius_find_code',
  'julius_find_all',
  'julius_trace_calls',
  'julius_file_api',
  'julius_repo_map',
  'julius_check_freshness',
] as const;

/**
 * The pre-0.8.1 tool names, still accepted. A name is an API: skills, saved
 * prompts and other people's notes reference the old ones, so they map to the
 * canonical name rather than 404.
 */
export const JULIUS_MCP_TOOL_ALIASES: Record<string, string> = {
  julius_ask: 'julius_find_code',
  julius_grep: 'julius_find_all',
  julius_callers: 'julius_trace_calls',
  julius_skeleton: 'julius_file_api',
  julius_map: 'julius_repo_map',
  julius_check: 'julius_check_freshness',
};

/** Every name julius answers to (canonical, legacy and julius's), lower-cased, for a
 *  membership test that anchors on the real vocabulary instead of a loose `includes('julius')`. */
export const JULIUS_MCP_TOOL_NAMES: ReadonlySet<string> = new Set(
  [...JULIUS_MCP_TOOL_CANONICAL, ...Object.keys(JULIUS_MCP_TOOL_ALIASES)].map((n) => n.toLowerCase()),
);

/** Canonical name for a requested tool: itself, its julius name, or what it was renamed to. */
export function canonicalToolName(name: string): string {
  return JULIUS_MCP_TOOL_ALIASES[name] ?? name;
}
