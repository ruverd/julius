/** Julius has one package, executable and host identity. */
import { existsSync, readFileSync, statSync } from 'node:fs';
import { delimiter, join } from 'node:path';
export type Brand = 'julius';
export const BRAND_ENV = 'JULIUS_INVOKED_AS';
export const PACKAGE_FOR: Record<Brand, string> = { julius: '@ruverd/julius' };
export function brand(_env: NodeJS.ProcessEnv = process.env): Brand { return 'julius'; }
export function setBrand(b: Brand, env: NodeJS.ProcessEnv = process.env): void { env[BRAND_ENV] = b; }
export function tag(_env: NodeJS.ProcessEnv = process.env): string { return '[julius]'; }
export function cmd(spelling: string, _b: Brand = brand()): string { return spelling; }
export function inBrand(text: string, _b: Brand = brand()): string { return text; }
export function repoWiredForJulius(dir: string): boolean {
  if (existsSync(join(dir, '.julius', 'hook.cjs'))) return true;
  if (existsSync(join(dir, '.claude', 'helpers', 'julius-hooks.cjs')) || existsSync(join(dir, '.claude', 'skills', 'julius', 'SKILL.md'))) return true;
  try { return readFileSync(join(dir, '.claude', 'settings.json'), 'utf8').includes('julius-hooks.cjs'); }
  catch { return false; }
}
export function adoptRepoBrand(_repo: string, env: NodeJS.ProcessEnv = process.env, _wiredElsewhere?: (repo: string) => boolean): Brand {
  setBrand('julius', env);
  return 'julius';
}
export function commandOnPath(name: string, env: NodeJS.ProcessEnv = process.env): boolean {
  const names = process.platform === 'win32' ? [`${name}.cmd`, `${name}.exe`, name] : [name];
  for (const dir of (env.PATH ?? '').split(delimiter)) {
    if (!dir) continue;
    for (const n of names) {
      try { if (statSync(join(dir, n)).isFile()) return true; } catch { /* not here */ }
    }
  }
  return false;
}
export function juliusOnPath(env: NodeJS.ProcessEnv = process.env): boolean { return commandOnPath('julius', env); }
