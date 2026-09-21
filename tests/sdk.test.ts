import { expect, test } from 'bun:test';
import { mkdtempSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Julius } from '../src/sdk';

test('observe and denied SDK requests do not persist original content', () => {
  const folder = mkdtempSync(join(tmpdir(), 'julius-sdk-'));
  const julius = new Julius(folder);
  try {
    const context = { projectId: 'p', category: 'tool_output', content: 'private content' };
    expect(julius.optimize(context, { mode: 'observe', version: '1.0.0' }).original).toBeNull();
    expect(julius.optimize(context, { mode: 'safe', version: '1.0.0', approved: false }).original).toBeNull();
    expect(readdirSync(join(folder, 'artifacts'))).toHaveLength(0);
  } finally { julius.close(); rmSync(folder, { recursive: true, force: true }); }
});
