#!/usr/bin/env bun
import { parseArgs } from 'node:util';
import { resolve } from 'node:path';
import { readFileSync, writeFileSync } from 'node:fs';
import { Julius } from './sdk';
import { doctor, discoverOllama } from './models';
import { report, renderText, renderCsv, renderHtml } from './reporting';
import { queryWindow } from './query';
import { validateEvent } from './events';
import { importClaudeTranscript, importCodexRollout } from './importers';

const help = `Julius 0.1.0 — local evidence-aware context tools

Usage: julius <command> [options]
  setup                              Detect clients; initialize local storage
  doctor                             Probe client versions without changing settings
  models list                        Discover installed/loaded Ollama models
  import <events.jsonl>               Validate and import Julius v1 events
  import <file> --format claude|codex --project <id> --source <id>
  optimize <file> --project <id>      Preview safe tool-output reduction
  restore <artifact-id> --project <id>
  artifacts delete <id> --project <id>
  artifacts purge --project <id>      Remove expired originals
  savings | usage                    Query effective ledger measurements
  export --format csv|json            Export aggregate evidence, not raw prompts
  dashboard --output <report.html>    Export self-contained accessible HTML
  run                                Unavailable: native agent execution not integrated
  integrations remove <id>            No integrations are installed by this version

Options:
  --data-dir <path>  Storage root (default JULIUS_HOME or .julius)
  --since 7d        Rolling days/hours/minutes, or ISO date/time
  --until <date>    Exclusive end; start is inclusive. Local dates convert to UTC.
  --project <id> --task <id> --model <id>
  --by model|category|client --json --explain
  --profile observe|safe  Optimizer profile (default observe)
  --endpoint <url>        Loopback Ollama endpoint

No report invokes a model. Optimize produces a candidate, never sends a request.
Token previews are heuristic estimates. This version has no verified native integration.
`;

export async function main(argv = process.argv.slice(2)): Promise<void> {
  const { values, positionals } = parseArgs({ args: argv, allowPositionals: true, strict: true, options: {
    'data-dir': { type: 'string' }, since: { type: 'string' }, until: { type: 'string' },
    project: { type: 'string' }, task: { type: 'string' }, model: { type: 'string' },
    by: { type: 'string' }, json: { type: 'boolean' }, explain: { type: 'boolean' },
    profile: { type: 'string' }, endpoint: { type: 'string' }, format: { type: 'string' },
    output: { type: 'string' }, help: { type: 'boolean' }, version: { type: 'boolean' },
    source: { type: 'string' },
  } });
  if (values.version) { console.log('julius-local 0.1.0 (repository: julius)'); return; }
  const command = positionals[0];
  if (values.help || !command) { console.log(help); return; }
  if (command === 'doctor') { console.log(JSON.stringify(await doctor(), null, 2)); return; }
  if (command === 'models' && positionals[1] === 'list') {
    console.log(JSON.stringify(await discoverOllama(values.endpoint), null, 2)); return;
  }
  if (command === 'run') throw new Error('Native execution is not integrated. Use the SDK in an authorized harness; Julius will not bypass client permissions.');
  if (command === 'integrations' && positionals[1] === 'remove') {
    console.log('No managed integrations exist. No client configuration was changed.'); return;
  }
  const allowed = ['setup', 'import', 'optimize', 'restore', 'artifacts', 'savings', 'usage', 'export', 'dashboard'];
  if (!allowed.includes(command)) throw new Error(`Unknown command: ${command}. Use --help.`);
  const directory = resolve(values['data-dir'] ?? process.env.JULIUS_HOME ?? '.julius');
  const julius = new Julius(directory);
  try {
    switch (command) {
      case 'setup':
        console.log(JSON.stringify({ product: 'julius-local', storage: directory, configurationChanges: [], doctor: await doctor() }, null, 2)); return;
      case 'import': {
        const path = required(positionals[1], 'JSONL file');
        const file = Bun.file(path);
        if (file.size > 16 * 1024 * 1024) throw new Error('Import exceeds 16 MiB limit.');
        const text = await file.text();
        const format = values.format ?? 'julius';
        if (!['julius', 'claude', 'codex'].includes(format)) throw new Error('Import --format must be julius, claude, or codex.');
        const events = format === 'julius'
          ? text.split(/\r?\n/).filter(line => line.trim()).map(line => validateEvent(JSON.parse(line)))
          : (format === 'claude' ? importClaudeTranscript : importCodexRollout)(text, { projectId: required(values.project, '--project'), sourceId: required(values.source, '--source') });
        const receipts = events.map(event => julius.ledger.record(event));
        console.log(JSON.stringify({ imported: receipts.filter(item => item.inserted).length, duplicates: receipts.filter(item => !item.inserted).length }, null, 2)); return;
      }
      case 'optimize': {
        const path = required(positionals[1], 'input file');
        const projectId = required(values.project, '--project');
        const mode = values.profile ?? 'observe';
        if (mode !== 'safe' && mode !== 'observe') throw new Error('Only observe and safe profiles are implemented.');
        if (Bun.file(path).size > 1024 * 1024) throw new Error('Tool output exceeds 1 MiB limit.');
        const result = julius.optimize({ projectId, content: readFileSync(path, 'utf8'), category: 'tool_output' }, { mode, version: '1.0.0', approved: mode === 'safe' });
        console.log(JSON.stringify(result, null, 2)); return;
      }
      case 'restore':
        process.stdout.write(julius.artifacts.get(required(values.project, '--project'), required(positionals[1], 'artifact ID'))); return;
      case 'artifacts':
        if (positionals[1] === 'purge') {
          console.log(JSON.stringify({ removed: julius.artifacts.purgeExpired(required(values.project, '--project')) })); return;
        }
        if (positionals[1] !== 'delete') throw new Error('Use artifacts delete <id> --project <id>.');
        julius.artifacts.delete(required(values.project, '--project'), required(positionals[2], 'artifact ID'));
        console.log('Original deleted. Metadata measurements may no longer be recountable.'); return;
      default: {
        const window = queryWindow(values);
        const by = values.by ?? (command === 'usage' ? 'category' : 'model');
        if (by !== 'model' && by !== 'category' && by !== 'client') throw new Error('--by must be model, category, or client.');
        const data = report(julius.ledger.events({ since: window.since, until: window.until, projectId: values.project, taskId: values.task, modelId: values.model }), window, by);
        if (command === 'dashboard') {
          const destination = resolve(required(values.output, '--output'));
          writeFileSync(destination, renderHtml(data), { flag: 'wx', mode: 0o600 });
          console.log(`Local HTML report written to ${destination}`); return;
        }
        if (command === 'export') {
          if (!['csv', 'json'].includes(values.format ?? 'csv')) throw new Error('--format must be csv or json.');
          console.log(values.format === 'json' ? JSON.stringify(data, null, 2) : renderCsv(data)); return;
        }
        console.log(values.json ? JSON.stringify(data, null, 2) : renderText(data));
      }
    }
  } finally { julius.close(); }
}
function required(value: string | undefined, name: string): string {
  if (!value) throw new Error(`Missing ${name}.`);
  return value;
}
if (import.meta.main) main().catch(error => { console.error(`Julius: ${error instanceof Error ? error.message : String(error)}`); process.exitCode = 1; });
