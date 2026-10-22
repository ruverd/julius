import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

test('offline benchmark checks fixed facts, recovery, full protocol costs and negative savings', () => {
  const home = mkdtempSync(join(tmpdir(), 'julius-benchmark-home-'));
  try {
    const r = spawnSync(process.execPath, ['scripts/benchmark-economy.mjs'], { encoding: 'utf8', env: { ...process.env, HOME: home, USERPROFILE: home, XDG_CONFIG_HOME: join(home, '.config') } });
    assert.equal(r.status, 0, r.stderr);
    const report = JSON.parse(r.stdout);
    assert.equal(report.encoding, 'cl100k_base'); assert.ok(report.fixtures.length >= 7);
    assert.equal(report.providerUsage, null);
    for (const fixture of report.fixtures) { assert.equal(fixture.factsVerified, true); assert.equal(fixture.roundTripVerified, true); assert.ok(fixture.julius.initialInterfaceTokens > 0); }
    assert.ok(report.fixtures.find((f: any) => f.name === 'all-original-needed').differenceVsInheritedStyle < 0);
    assert.equal(report.fixtures.find((f: any) => f.name === 'pathological-unknown').rawOutputTokens, null);
    assert.doesNotMatch(r.stdout, /\/Users\/|\/home\/|\/private\/var\//);
  } finally { rmSync(home, { recursive: true, force: true }); }
});
