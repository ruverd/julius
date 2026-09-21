import { expect, test } from 'bun:test';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { EconomyEvent } from '../src/events';

test('CLI lifecycle keeps candidates separate from observed savings and restores originals', () => {
  const root = mkdtempSync(join(tmpdir(), 'julius-integration-'));
  const dataDir = join(root, 'data');
  const cli = join(import.meta.dir, '..', 'src', 'cli.ts');
  const run = (...args: string[]) => {
    const p = Bun.spawnSync(['bun', cli, ...args, '--data-dir', dataDir], { cwd: root });
    return { code: p.exitCode, out: new TextDecoder().decode(p.stdout), err: new TextDecoder().decode(p.stderr) };
  };
  try {
    const setup = run('setup');
    expect(setup.code).toBe(0);
    expect(JSON.parse(setup.out).configurationChanges).toEqual([]);

    const original = Array(6).fill('neutral status line with enough characters to reduce and some additional ordinary status detail').join('\n');
    const input = join(root, 'tool.txt');
    writeFileSync(input, original);
    const preview = run('optimize', input, '--project', 'p', '--profile', 'safe');
    expect(preview.code).toBe(0);
    const optimized = JSON.parse(preview.out);
    expect(optimized.receipt.applied).toBe(true);
    expect(optimized.receipt.realizedSavings).toBeNull();
    expect(optimized.receipt.evidence).toBe('heuristic_estimate');
    expect(optimized.candidate).toContain(optimized.original.id);
    expect(run('restore', optimized.original.id, '--project', 'p').out).toBe(original);
    expect(run('restore', optimized.original.id, '--project', 'other').code).not.toBe(0);

    const usage: EconomyEvent = {
      schemaVersion: 1, eventId: crypto.randomUUID(), occurredAt: new Date().toISOString(),
      sourceId: 'fixture', sourceEventId: 'usage-1', projectId: 'p', taskId: null,
      sessionId: 's', requestId: 'r1', attemptId: 'a1', clientId: '<client>', adapterVersion: '1',
      modelId: null, providerId: null, executionLocation: 'unknown', evidence: 'provider_reported',
      eventType: 'usage', payload: { inputTokens: 100, outputTokens: 10, cacheReadTokens: null,
        cacheWriteTokens: null, complete: true, category: 'primary', callId: 'call-1', costUsd: null },
    };
    const eventsFile = join(root, 'events.jsonl');
    writeFileSync(eventsFile, `${JSON.stringify(usage)}\n`);
    expect(JSON.parse(run('import', eventsFile).out).imported).toBe(1);
    expect(JSON.parse(run('import', eventsFile).out).duplicates).toBe(1);
    const savings = JSON.parse(run('savings', '--json').out);
    expect(savings.observedCalls).toBe(1);
    expect(savings.directInputReduction).toEqual([]);
    expect(savings.modeledCostUsd.total).toBeNull();
    expect(savings.financialSavingsUsd).toBeNull();
    expect(JSON.parse(run('export', '--format', 'json').out).groups.length).toBe(1);

    const dashboard = join(root, 'report.html');
    expect(run('dashboard', '--output', dashboard, '--by', 'client').code).toBe(0);
    const html = readFileSync(dashboard, 'utf8');
    expect(html).toContain('&lt;client&gt;');
    expect(html).not.toContain('<client>');
    expect(html).not.toContain(original);

    expect(run('artifacts', 'delete', optimized.original.id, '--project', 'p').code).toBe(0);
    expect(run('restore', optimized.original.id, '--project', 'p').code).not.toBe(0);
    expect(run('optimize', input, '--project', 'p', '--profile', 'invalid').code).not.toBe(0);
    expect(run('run').code).not.toBe(0);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
