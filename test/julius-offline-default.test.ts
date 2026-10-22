import assert from 'node:assert/strict';
import { test } from 'node:test';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { juliusUrl, cloudEnabled } from '../src/cloud/workspace.js';
import { telemetryOn } from '../src/telemetry/gate.js';

test('fresh Julius has no implicit cloud endpoint or telemetry consent', () => {
  const home = mkdtempSync(join(tmpdir(), 'julius-default-'));
  const old = process.env.JULIUS_POSTHOG_KEY;
  try {
    process.env.JULIUS_POSTHOG_KEY = 'test-key';
    assert.equal(juliusUrl({}), '');
    assert.equal(cloudEnabled({ JULIUS_HOME: home }), false);
    assert.equal(telemetryOn(home, {}), false);
  } finally {
    if (old === undefined) delete process.env.JULIUS_POSTHOG_KEY; else process.env.JULIUS_POSTHOG_KEY = old;
    rmSync(home, { recursive: true, force: true });
  }
});

test('normal startup with a fresh home neither contacts transport nor schedules an external child', () => {
  const home = mkdtempSync(join(tmpdir(), 'julius-offline-'));
  const probe = join(home, 'probe.cjs');
  const log = join(home, 'transport.log');
  writeFileSync(probe, `const fs=require('node:fs'); const log=${JSON.stringify(log)};
    const fail=(kind)=>{ fs.appendFileSync(log,kind+'\\n'); throw new Error('Unexpected external transport: '+kind); };
    globalThis.fetch=()=>fail('fetch');
    for(const name of ['node:http','node:https']) { const m=require(name); m.request=()=>fail(name); m.get=()=>fail(name); }
    const cp=require('node:child_process'); const spawn=cp.spawn;
    cp.spawn=(cmd,args,opts)=> { if(args?.some(x=>/_update-check|_telemetry-flush|_cloud/.test(x))) return fail(args.join(' ')); return spawn(cmd,args,opts); };
    require('node:module').syncBuiltinESMExports();
  `);
  try {
    const env: NodeJS.ProcessEnv = { ...process.env, HOME: home, USERPROFILE: home, NODE_OPTIONS: `--require ${probe}` };
    for (const key of Object.keys(env)) if (/^(CI$|JULIUS_|GRAFT_|TRAIL_|DO_NOT_TRACK$|GITHUB_ACTIONS$)/.test(key)) delete env[key];
    const result = spawnSync(process.execPath, ['--import', 'tsx', 'src/cli.ts', 'telemetry', 'status'], { encoding: 'utf8', env });
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout + result.stderr, /off/);
    assert.equal(existsSync(log) ? readFileSync(log, 'utf8') : '', '');
  } finally { rmSync(home, { recursive: true, force: true }); }
});
