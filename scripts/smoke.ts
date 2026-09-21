import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const directory = mkdtempSync(join(tmpdir(), 'julius-binary-smoke-'));
const binary = resolve('dist/julius');
function run(args: string[], demo = false): string {
  const result = Bun.spawnSync(demo ? [process.execPath, 'examples/demo.ts'] : [binary, ...args], {
    env: { ...process.env, JULIUS_HOME: directory }, stdout: 'pipe', stderr: 'pipe',
  });
  if (result.exitCode !== 0) throw new Error(result.stderr.toString());
  return result.stdout.toString();
}
try {
  if (!run(['--version']).includes('julius-local 0.1.0')) throw new Error('Unexpected binary identity');
  run([], true);
  run([], true);
  const args = ['--since', '2026-09-21T00:00:00Z', '--until', '2026-09-22T00:00:00Z'];
  const data = JSON.parse(run(['savings', ...args, '--json']));
  if (data.observedCalls !== 1 || data.directInputReduction[0]?.tokens.total !== 7000 || data.financialSavingsUsd !== null) throw new Error('Invalid compiled report');
  run(['dashboard', ...args, '--output', join(directory, 'report.html')]);
  run(['export', ...args, '--format', 'csv']);
  console.log('Compiled executable smoke passed: identity, idempotent import, 7,000 marginal reduction, unknown money, HTML and CSV.');
} finally { rmSync(directory, { recursive: true, force: true }); }
