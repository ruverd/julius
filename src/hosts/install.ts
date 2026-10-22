/** Global MCP ownership transaction. Unlike inherited init's best-effort writers,
 * this layer snapshots all targets and refuses to overwrite changed ownership. */
import { existsSync, realpathSync, readFileSync, writeFileSync, mkdirSync, rmSync, lstatSync, readdirSync, renameSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { parse as parseToml } from 'smol-toml';
import { isDeepStrictEqual } from 'node:util';

export type InstallHost = 'claude' | 'cursor' | 'codex' | 'grok';
interface Change { path: string; before: string | null; after: string | null; kind: 'config' | 'copy' | 'state' }
interface Owned { path: string; before: string | null; after: string; keys: string[] }
interface Manifest { version: 1; configs: Owned[]; migrationRepos?: string[] }
export interface InstallOptions {
  home: string; hosts?: string[]; dryRun?: boolean; migrateTrail?: string;
  /** Fault-injection seam; never an environment-controlled production behavior. */
  afterWrite?: (path: string, index: number) => void;
}
const targets = (home: string): Record<InstallHost, string> => ({ claude: join(home, '.claude.json'), cursor: join(home, '.cursor', 'mcp.json'), codex: join(home, '.codex', 'config.toml'), grok: join(home, '.grok', 'config.toml') });
const statePath = (home: string) => join(home, '.julius', 'install', 'manifest.json');
function safePath(path: string): void {
  for (let p = resolve(path);; p = dirname(p)) {
    try { if (lstatSync(p).isSymbolicLink()) throw new Error(`Refusing symbolic link: ${p}`); }
    catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error; }
    if (dirname(p) === p) break;
  }
}
function read(path: string): string | null {
  safePath(path);
  try { return readFileSync(path).toString('base64'); } catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null; throw error; }
}
const decode = (bytes: string | null) => bytes === null ? '' : Buffer.from(bytes, 'base64').toString('utf8');
const encode = (text: string) => Buffer.from(text).toString('base64');
function json(bytes: string | null): Record<string, any> {
  const value = bytes === null ? {} : JSON.parse(Buffer.from(bytes, 'base64').toString('utf8'));
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Expected a JSON object');
  if (value.mcpServers !== undefined && (!value.mcpServers || typeof value.mcpServers !== 'object' || Array.isArray(value.mcpServers))) throw new Error('Expected mcpServers object');
  return value;
}
function load(home: string, bytes: string | null): Manifest {
  if (bytes === null) return { version: 1, configs: [] };
  const manifest = json(bytes) as Manifest;
  const allowed = new Set(Object.values(targets(home)));
  if (manifest.migrationRepos !== undefined && (!Array.isArray(manifest.migrationRepos) || manifest.migrationRepos.some(repo => typeof repo !== 'string' || resolve(repo) !== repo))) throw new Error('Invalid migration manifest');
  for (const repo of manifest.migrationRepos ?? []) for (const path of repoMcpPaths(repo)) allowed.add(path);
  if (manifest.version !== 1 || !Array.isArray(manifest.configs) || manifest.configs.some(c => !allowed.has(c.path) || typeof c.after !== 'string' || !(c.before === null || typeof c.before === 'string') || !Array.isArray(c.keys) || c.keys.some(k => !['julius', 'trail'].includes(k)))) throw new Error('Invalid install manifest');
  return manifest;
}
/** Narrow table editor: preserve foreign TOML verbatim, reject ambiguous owned
 * dotted/quoted/inline forms rather than pretending to parse arbitrary TOML. */
function tomlSection(text: string, name = 'julius'): { start: number; end: number; text: string } | null {
  parseToml(text);
  if (text.includes('\"\"\"') || text.includes("'''")) throw new Error('Multiline TOML requires manual MCP setup; no files changed');
  const header = new RegExp(`^\\[mcp_servers\\.${name}\\][ \\t]*(?:#[^\\n]*)?\\r?$`, 'gm');
  const matches = [...text.matchAll(header)];
  const suspicious = text.split('\n').some(line => line.includes(name) &&
    /^(?:\s*\[|\s*(?:mcp_servers|["']?(?:julius|trail)["']?)\s*[.=])/.test(line) &&
    !new RegExp(`^\\[mcp_servers\\.${name}\\][ \\t]*(?:#.*)?\\r?$`).test(line));
  if (matches.length > 1 || suspicious) throw new Error(`Unsupported or duplicate ${name} TOML section; resolve it manually before setup`);
  if (!matches.length) return null;
  const start = matches[0].index!;
  const afterHeader = start + matches[0][0].length;
  const next = text.slice(afterHeader).search(/^\s*\[/m);
  const end = next < 0 ? text.length : afterHeader + next;
  // Whitespace separating tables is not owned.
  const owned = text.slice(start, end).replace(/\s+$/, '') + '\n';
  return { start, end: start + text.slice(start, end).trimEnd().length + (text[start + text.slice(start, end).trimEnd().length] === '\n' ? 1 : 0), text: owned };
}
function replaceToml(text: string, section: string, name = 'julius'): string {
  const old = tomlSection(text, name);
  const updated = old ? text.slice(0, old.start) + section + text.slice(old.end)
    : section ? text + (text && !text.endsWith('\n') ? '\n' : '') + section : text;
  // Valid input can still conflict with an appended table (quoted dotted keys,
  // or a scalar mcp_servers). Validate the complete proposal before any write.
  parseToml(updated);
  return updated;
}
function assertOwned(current: string | null, owned: Owned): void {
  if (owned.path.endsWith('.toml')) {
    for (const key of owned.keys) if (tomlSection(decode(current), key)?.text !== tomlSection(decode(owned.after), key)?.text) throw new Error(`Owned configuration conflict: ${owned.path}`);
    return;
  }
  const now = json(current).mcpServers ?? {}; const installed = json(owned.after).mcpServers ?? {};
  for (const key of owned.keys) if (!isDeepStrictEqual(now[key], installed[key])) throw new Error(`Owned configuration conflict: ${owned.path} (${key})`);
}
function write(path: string, value: string | null): void {
  safePath(path);
  if (value === null) { rmSync(path, { force: true }); return; }
  mkdirSync(dirname(path), { recursive: true });
  const temp = `${path}.${randomUUID()}.tmp`;
  try { writeFileSync(temp, Buffer.from(value, 'base64'), { flag: 'wx', mode: 0o600 }); renameSync(temp, path); }
  finally { rmSync(temp, { force: true }); }
}
function transact(changes: Change[], opts: InstallOptions): string[] {
  const pending = changes.filter(c => c.before !== c.after);
  const report = pending.map(c => `${opts.dryRun ? 'Would update' : 'Updated'} ${c.path}`);
  if (opts.dryRun || !pending.length) return report.length ? report : ['Already up to date'];
  const lock = join(opts.home, '.julius', 'install', 'lock'); safePath(lock); mkdirSync(dirname(lock), { recursive: true });
  try { mkdirSync(lock); } catch (error) { if ((error as NodeJS.ErrnoException).code === 'EEXIST') throw new Error('Another install transaction is active; inspect .julius/install/lock before retrying'); throw error; }
  const journal = join(dirname(lock), 'transaction.json'); const done: Change[] = [];
  try {
    if (existsSync(journal)) throw new Error('Unresolved install transaction; inspect transaction.json before retrying');
    for (const c of pending) if (read(c.path) !== c.before) throw new Error(`Concurrent configuration conflict: ${c.path}`);
    write(journal, encode(JSON.stringify(pending)));
    try {
      for (const c of pending) {
        if (read(c.path) !== c.before) throw new Error(`Concurrent configuration conflict: ${c.path}`);
        write(c.path, c.after); done.push(c); opts.afterWrite?.(c.path, done.length);
      }
    } catch (error) {
      const conflicts: string[] = [];
      for (const c of done.reverse()) {
        if (read(c.path) === c.after) write(c.path, c.before);
        else conflicts.push(c.path);
      }
      if (conflicts.length) throw new Error(`Rollback conflict; preserved concurrent edits and transaction.json: ${conflicts.join(', ')}; ${String(error)}`);
      rmSync(journal); throw error;
    }
    rmSync(journal); return report;
  } finally { rmSync(lock, { recursive: true, force: true }); }
}
function legacyTrail(entry: unknown): boolean {
  // Only exact upstream launch forms, with no unknown settings or extra args.
  return isDeepStrictEqual(entry, { command: 'trail', args: ['mcp'] }) ||
    isDeepStrictEqual(entry, { command: 'npx', args: ['-y', '@trailhq/trail-code', 'mcp'] });
}
const repoMcpPaths = (repo: string) => [join(repo, '.mcp.json'), join(repo, '.cursor', 'mcp.json')];
function migration(repo: string): Change[] {
  repo = realpathSync(repo);
  const from = join(resolve(repo), '.trail', 'learnings'); const to = join(resolve(repo), '.julius', 'learnings');
  safePath(from); safePath(to);
  if (!existsSync(from)) return [];
  const changes: Change[] = []; let count = 0;
  const walk = (source: string, dest: string): void => {
    for (const entry of readdirSync(source, { withFileTypes: true })) {
      if (++count > 10000) throw new Error('Migration exceeds 10000 entries');
      const src = join(source, entry.name), path = join(dest, entry.name);
      if (entry.isSymbolicLink()) throw new Error(`Migration refuses symbolic link: ${src}`);
      if (entry.isDirectory()) walk(src, path);
      else if (entry.isFile()) {
        const after = read(src)!; const before = read(path);
        if (before !== null && before !== after) throw new Error(`Migration conflict: ${path}`);
        changes.push({ path, before, after, kind: 'copy' });
      } else throw new Error(`Unsupported migration file: ${src}`);
    }
  };
  walk(from, to); return changes;
}
export function installGlobal(opts: InstallOptions): string[] {
  const home = realpathSync(opts.home); opts = { ...opts, home }; const paths = targets(home);
  const hosts = opts.hosts ?? (Object.keys(paths) as InstallHost[]).filter(id => existsSync(join(home, `.${id}`)) || existsSync(paths[id]));
  if (!hosts.length) throw new Error('No supported host detected. Select --hosts claude,cursor,codex,grok explicitly.');
  for (const id of hosts) if (!Object.hasOwn(paths, id)) throw new Error(`Unsupported host: ${id}; supported: claude,cursor,codex,grok`);
  const binary = fileURLToPath(new URL('../../dist/bin/julius.js', import.meta.url));
  // Both src/hosts and dist/hosts resolve to package/dist/bin, independent of cwd.
  if (!existsSync(binary)) throw new Error('Build Julius before installing: npm run build');
  const entry = { command: process.execPath, args: [binary, 'mcp'] };
  const manifestBefore = read(statePath(home));
  const manifest = load(home, manifestBefore); const changes = opts.migrateTrail ? migration(opts.migrateTrail) : [];
  if (opts.migrateTrail) {
    const repo = realpathSync(opts.migrateTrail);
    manifest.migrationRepos = [...new Set([...(manifest.migrationRepos ?? []), repo])];
    for (const path of repoMcpPaths(repo)) {
      const before = read(path); if (before === null) continue;
      const root = json(before); const servers = root.mcpServers ?? {};
      const old = manifest.configs.find(c => c.path === path); if (old) assertOwned(before, old);
      const keys = new Set(old?.keys ?? []);
      if (legacyTrail(servers.trail)) { delete servers.trail; keys.add('trail'); }
      if (!keys.size) continue;
      const after = isDeepStrictEqual(root, json(before)) ? before : encode(JSON.stringify(root, null, 2) + '\n');
      const owned = { path, before: old ? restoreOwned(before, old) : before, after, keys: [...keys] };
      if (old) manifest.configs[manifest.configs.indexOf(old)] = owned; else manifest.configs.push(owned);
      changes.push({ path, before, after, kind: 'config' });
    }
  }
  for (const id of new Set(hosts)) {
    const path = paths[id as InstallHost]; const before = read(path);
    const old = manifest.configs.find(c => c.path === path); if (old) assertOwned(before, old);
    if (id === 'codex' || id === 'grok') {
      const section = `[mcp_servers.julius]\ncommand = ${JSON.stringify(entry.command)}\nargs = ${JSON.stringify(entry.args)}\n`;
      let text = decode(before); const keys = new Set(old?.keys ?? ['julius']);
      if (opts.migrateTrail) {
        const parsed = parseToml(text); const servers = parsed.mcp_servers as Record<string, unknown> | undefined;
        if (legacyTrail(servers?.trail === undefined ? undefined : JSON.parse(JSON.stringify(servers.trail)))) { text = replaceToml(text, '', 'trail'); keys.add('trail'); }
      }
      const after = encode(replaceToml(text, section));
      const owned = { path, before: old ? restoreOwned(before, old) : before, after, keys: [...keys] };
      if (old) manifest.configs[manifest.configs.indexOf(old)] = owned; else manifest.configs.push(owned);
      changes.push({ path, before, after, kind: 'config' }); continue;
    }
    const root = json(before);
    const servers = root.mcpServers ??= {}; const keys = new Set(old?.keys ?? ['julius']);
    if (opts.migrateTrail && legacyTrail(servers.trail)) { delete servers.trail; keys.add('trail'); }
    servers.julius = entry;
    const after = isDeepStrictEqual(root, json(before)) ? before! : encode(JSON.stringify(root, null, 2) + '\n');
    const owned = { path, before: old ? restoreOwned(before, old) : before, after, keys: [...keys] };
    if (old) manifest.configs[manifest.configs.indexOf(old)] = owned; else manifest.configs.push(owned);
    changes.push({ path, before, after, kind: 'config' });
  }
  const path = statePath(home); changes.push({ path, before: manifestBefore, after: encode(JSON.stringify(manifest, null, 2) + '\n'), kind: 'state' });
  return transact(changes, opts);
}
function restoreOwned(before: string | null, owned: Owned): string | null {
    let after = owned.before;
    if (before !== owned.after && owned.path.endsWith('.toml')) {
      let text = decode(before);
      for (const key of owned.keys) text = replaceToml(text, tomlSection(decode(owned.before), key)?.text ?? '', key);
      after = encode(text);
    } else if (before !== owned.after) {
      const root = json(before); const original = json(owned.before); const servers = root.mcpServers ??= {};
      for (const key of owned.keys) {
        if (Object.hasOwn(original.mcpServers ?? {}, key)) servers[key] = original.mcpServers[key]; else delete servers[key];
      }
      if (!Object.keys(servers).length && original.mcpServers === undefined) delete root.mcpServers;
      after = encode(JSON.stringify(root, null, 2) + '\n');
    }
  return after;
}
export function uninstallGlobal(opts: InstallOptions): string[] {
  const home = realpathSync(opts.home); opts = { ...opts, home }; const manifestBefore = read(statePath(home));
  const manifest = load(home, manifestBefore); const changes: Change[] = [];
  for (const owned of manifest.configs) {
    const before = read(owned.path); assertOwned(before, owned);
    const after = restoreOwned(before, owned);
    changes.push({ path: owned.path, before, after, kind: 'config' });
  }
  const path = statePath(home); changes.push({ path, before: manifestBefore, after: null, kind: 'state' });
  return transact(changes, opts);
}
