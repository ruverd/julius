import { runInvestigation, deliverInvestigation, type InvestigationArgs } from '../investigation/index.js';
import { TOOLS, callTool, type ToolDef } from './tools.js';
import { Economy, ECONOMY_MAX_BYTES } from '../economy/index.js';
import { selectDelivery } from '../economy/delivery.js';
import { hasJuliusIndex } from '../graph/root.js';
import { buildGraph } from '../graph/build.js';
import { wiringPath } from '../graph/write.js';
import { contextDirFor } from '../context/node-file.js';
import { existsSync } from 'node:fs';

const string = { type: 'string', minLength: 1, maxLength: 4096 };
const integer = (maximum: number, minimum = 0) => ({ type: 'integer', minimum, maximum });
const object = (properties: object, required: string[] = []) => ({ type: 'object', properties, required, additionalProperties: false });
export const OPERATIONS: ToolDef[] = [
  { name: 'investigation.execute', description: 'Investigate change impact or locate literal failure evidence locally in one call; reuse verified results. Experimental structural evidence, not proof of correctness.', inputSchema: object({ recipe: { enum: ['change-impact', 'failure-localization'] }, paths: { type: 'array', minItems: 1, maxItems: 32, items: string }, query: { type: 'string', minLength: 1, maxLength: 512 }, depth: integer(8, 1) }, ['recipe']) },
  { name: 'julius_find_code', description: 'Rank code by query.', inputSchema: object({ query: string, limit: integer(100, 1), full: { type: 'boolean' }, in: string }, ['query']) },
  { name: 'julius_file_api', description: 'File signatures and source locations.', inputSchema: object({ file: string }, ['file']) },
  { name: 'julius_check_freshness', description: 'Report graph drift.', inputSchema: object({}) },
  { name: 'julius_trace_calls', description: 'Call/reference edges and transitive impact.', inputSchema: object({ symbol: string, direction: { enum: ['in', 'out'] }, depth: { anyOf: [integer(100, 1), { enum: ['all'] }] }, in: string }, ['symbol']) },
  { name: 'julius_find_all', description: 'Search indexed source, grouped by symbol.', inputSchema: object({ pattern: string, in: string, ignore_case: { type: 'boolean' }, fixed: { type: 'boolean' } }, ['pattern']) },
  { name: 'julius_repo_map', description: 'Structural repository orientation.', inputSchema: object({ max_dirs: integer(100, 1) }) },
  { name: 'context.capture', description: 'Bound supplied text; retain omitted bytes locally.', inputSchema: object({ content: { type: 'string', maxLength: ECONOMY_MAX_BYTES } }, ['content']) },
  { name: 'context.read', description: 'Recover a byte range or search a retained handle.', inputSchema: object({ handle: { type: 'string', pattern: '^sha256:[a-f0-9]{64}$' }, start: integer(ECONOMY_MAX_BYTES), end: integer(ECONOMY_MAX_BYTES), search: string }, ['handle']) },
  { name: 'context.stats', description: 'Local payload ledger; excludes protocol costs, not billing.', inputSchema: object({}) },
];
export const COMPACT_TOOLS: ToolDef[] = [
  { name: 'julius_discover', description: 'Discover local code investigation, impact analysis, failure localization and graph/context operations; fetch one schema.', inputSchema: object({ operation: string }) },
  { name: 'julius_call', description: 'Run a discovered local investigation or graph/context operation. No shell or arbitrary code execution.', inputSchema: object({ operation: string, args: { type: 'object' }, budget: integer(16000, 256), delivery: { enum: ['selective', 'complete'] }, focus: { type: 'string', minLength: 1, maxLength: 512 } }, ['operation']) },
];
export const COMPACT_INSTRUCTIONS = 'For code changes or debugging, discover investigation.execute and use its change-impact (paths) or failure-localization (literal query) recipe before repeated file reads. Invoke tools yourself; never ask the user to run Julius commands. Use julius_discover for other graph/context schemas, then julius_call. Results are bounded (default 1200 cl100k_base text tokens); recover omitted content with context.read and byte ranges/search. Graph calls build a local structural index lazily, without model calls. Context operations need no graph. Budget excludes MCP framing. Payload accounting is not provider billing; full recovery can cost more than raw output.';

function validate(value: unknown, schema: any, path = 'arguments'): void {
  if (schema.anyOf) {
    for (const candidate of schema.anyOf) { try { validate(value, candidate, path); return; } catch {} }
    throw new Error(`${path}: invalid value`);
  }
  if (schema.enum && !schema.enum.includes(value)) throw new Error(`${path}: invalid enum value`);
  if (schema.type === 'object') {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${path}: expected object`);
    const record = value as Record<string, unknown>;
    for (const key of schema.required ?? []) if (!Object.hasOwn(record, key)) throw new Error(`${path}.${key}: required`);
    for (const [key, v] of Object.entries(record)) {
      if (!Object.hasOwn(schema.properties ?? {}, key)) { if (schema.additionalProperties === false) throw new Error(`${path}.${key}: unknown argument`); }
      else validate(v, schema.properties[key], `${path}.${key}`);
    }
  } else if (schema.type === 'array') {
    if (!Array.isArray(value) || value.length < (schema.minItems ?? 0) || value.length > (schema.maxItems ?? Infinity)) throw new Error(`${path}: invalid array`);
    value.forEach((v, i) => validate(v, schema.items, `${path}[${i}]`));
  } else if (schema.type === 'string') {
    if (typeof value !== 'string' || value.length < (schema.minLength ?? 0) || value.length > (schema.maxLength ?? Infinity) || (schema.pattern && !new RegExp(schema.pattern).test(value))) throw new Error(`${path}: invalid string`);
  } else if (schema.type === 'integer') {
    if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < schema.minimum || value > schema.maximum) throw new Error(`${path}: invalid integer`);
  } else if (schema.type === 'boolean' && typeof value !== 'boolean') throw new Error(`${path}: expected boolean`);
}

const builds = new Map<string, Promise<unknown>>();
async function ensureGraph(root: string, dir?: string): Promise<void> {
  if (dir ? existsSync(wiringPath(contextDirFor(root, dir))) : hasJuliusIndex(root)) return;
  const key = contextDirFor(root, dir);
  let pending = builds.get(key);
  if (!pending) { pending = buildGraph(root, { contextDir: dir }); builds.set(key, pending); }
  try { await pending; } finally { builds.delete(key); }
}

export async function callCompact(root: string, name: string, input: unknown, dir?: string): Promise<{ text: string; isError: boolean }> {
  try {
    const tool = COMPACT_TOOLS.find(t => t.name === name);
    if (!tool) throw new Error(`Unknown compact tool: ${name}; use julius_discover`);
    validate(input, tool.inputSchema);
    const params = input as { operation?: string; args?: Record<string, unknown>; budget?: number; delivery?: string; focus?: string };
    if (name === 'julius_discover') {
      const selected = params.operation === undefined ? undefined : OPERATIONS.find(o => o.name === params.operation);
      if (params.operation !== undefined && !selected) throw new Error(`Unknown operation: ${params.operation}`);
      return { text: JSON.stringify(selected ?? OPERATIONS.map(({ name, description }) => ({ name, description }))), isError: false };
    }
    const operation = OPERATIONS.find(o => o.name === params.operation);
    if (!operation) throw new Error(`Unknown operation: ${params.operation}`);
    const args = params.args ?? {}; validate(args, operation.inputSchema);
    const choice = selectDelivery({ delivery: params.delivery, focus: params.focus, budget: params.budget, args });
    const economy = new Economy(root);
    if (operation.name === 'context.capture') return { text: (await economy.present(args.content as string, choice, 'mcp')).text, isError: false };
    if (operation.name === 'context.read') return { text: (await economy.read(args.handle as string, { budget: choice.budget ?? 1200, transport: 'mcp', start: args.start as number | undefined, end: args.end as number | undefined, search: args.search as string | undefined })).text, isError: false };
    if (operation.name === 'context.stats') return { text: JSON.stringify(await economy.stats()), isError: false };
    if (operation.name === 'investigation.execute') return { text: await deliverInvestigation(root, await runInvestigation(root, args as unknown as InvestigationArgs, dir), choice.budget ?? 1200), isError: false };
    if (!TOOLS.some(t => t.name === operation.name)) throw new Error('Unsupported graph operation');
    await ensureGraph(root, dir);
    const result = await callTool(root, operation.name, args, dir);
    return { text: (await economy.present(result.text, choice, 'mcp')).text, isError: result.isError };
  } catch (error) { return { text: error instanceof Error ? error.message : String(error), isError: true }; }
}
