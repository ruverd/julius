import { closeSync, constants, fstatSync, openSync, readFileSync, realpathSync } from 'node:fs';
import { isAbsolute, relative } from 'node:path';
import { walkDir } from '../ingest/fs.js';
import { contentHash } from '../util/id.js';
import { readBuildConfig, type BuildConfig } from '../util/state.js';

export interface GraphVerification {
  graphHash: string;
  configurationHash: string;
}

export function isGraphConfigurationFile(path: string): boolean {
  return /(?:^|[/\\])(?:package(?:-lock)?\.json|tsconfig[^/\\]*\.json|jsconfig\.json|go\.(?:mod|sum)|Cargo\.(?:toml|lock)|\.gitignore)$/.test(path);
}

export function graphConfigurationHash(config: Array<[string, string]>, onlyDirs: string[] | undefined, buildConfig: BuildConfig | null): string {
  // Ignore rules are checked through exact source/config membership. A normal
  // build may append its own cache exclusion without changing that membership.
  const resolution = config.filter(([path]) => !/(?:^|[/\\])\.gitignore$/.test(path));
  return contentHash(JSON.stringify({ config: resolution, onlyDirs: onlyDirs?.length ? onlyDirs : undefined, buildConfig }));
}

/** Best-effort provenance; unsupported configuration leaves the index unverified. */
export function readGraphConfigurationHash(root: string, onlyDirs?: string[], paths?: string[]): string | null {
  try {
    const canonicalRoot = realpathSync(root);
    const config: Array<[string, string]> = [];
    let total = 0;
    for (const path of (paths ?? walkDir(root)).filter(isGraphConfigurationFile).sort()) {
      if (/(?:^|[/\\])\.gitignore$/.test(path)) continue;
      const rel = relative(canonicalRoot, realpathSync(path));
      if (isAbsolute(rel) || rel === '..' || rel.startsWith('../') || rel.startsWith('..\\')) return null;
      const fd = openSync(path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0) | (constants.O_NONBLOCK ?? 0));
      try {
        const stat = fstatSync(fd);
        if (!stat.isFile() || stat.size > 1024 * 1024) return null;
        const raw = readFileSync(fd);
        total += raw.length;
        if (total > 32 * 1024 * 1024) return null;
        config.push([relative(root, path), contentHash(raw.toString('base64'))]);
      } finally { closeSync(fd); }
    }
    return graphConfigurationHash(config, onlyDirs, readBuildConfig(root));
  } catch { return null; }
}
