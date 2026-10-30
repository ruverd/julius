// Experiment-only process accounting, also used by the real CLI and MCP server.
process.on('exit', () => {
  if (process.env.JULIUS_SELECTIVE_RESOURCES) require('node:fs').writeFileSync(
    process.env.JULIUS_SELECTIVE_RESOURCES,
    JSON.stringify({ maxRSSKiB: process.resourceUsage().maxRSS, memory: process.memoryUsage() }),
  );
});
