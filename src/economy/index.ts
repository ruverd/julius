import { spawn } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { mkdirSync, lstatSync, readFileSync, writeFileSync, readdirSync, renameSync, linkSync, unlinkSync, openSync, closeSync, fstatSync, rmSync, constants } from 'node:fs';
import { resolve, join } from 'node:path';
import { get_encoding } from 'tiktoken';

let encoding: ReturnType<typeof get_encoding> | undefined;
export const ECONOMY_ENCODING = 'cl100k_base';
export const ECONOMY_MAX_BYTES = 8 * 1024 * 1024;
function countPayloadTokens(text: string): number | null {
  // Long BPE pieces can take quadratic time, including in WASM. Keep recovery
  // independent from accounting when an adversarial payload exceeds this bound.
  for (const match of text.matchAll(/\s+|\S+/gu)) if (match[0].length > 4096) return null;
  return (encoding ??= get_encoding('cl100k_base')).encode(text, [], []).length;
}
export function economyTokens(text: string): number {
  const count = countPayloadTokens(text);
  if (count === null) throw new Error('Exact token count unavailable: whitespace or non-whitespace run exceeds 4096 UTF-16 units');
  return count;
}
export interface CaptureOptions { budget: number }
export interface ReadOptions extends CaptureOptions { start?: number; end?: number; search?: string; raw?: boolean }
export interface EconomyResult { text: string; handle: string | null; bytes: Buffer; omittedBytes: number }
export interface RunOptions extends CaptureOptions { maxBytes?: number; timeoutMs?: number }
export interface RunResult { text: string; status: number | null; signal: NodeJS.Signals | null; stdoutHandle: string; stderrHandle: string; complete: boolean; limit: 'bytes' | 'timeout' | null }
export interface EconomyStats { encoding: string; rawTokens: number | null; deliveredTokens: number | null; savedTokens: number | null; events: number; accountedEvents: number; uncountedEvents: number; rawUncountedEvents: number; deliveredUncountedEvents: number; method: string; scope: string }

function budgetCheck(budget: number): void {
  if (!Number.isSafeInteger(budget) || budget < 1 || budget > 1_000_000) throw new Error('budget must be an integer from 1 to 1000000');
}
function representation(bytes: Buffer): { content: string; format: string } {
  try { return { content: new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes), format: 'utf8' }; }
  catch { return { content: bytes.toString('base64'), format: 'base64' }; }
}
function digest(bytes: Buffer): string { return createHash('sha256').update(bytes).digest('hex'); }
function safeDirectory(path: string): void {
  try { mkdirSync(path); } catch (error) { if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error; }
  const stat = lstatSync(path);
  if (stat.isSymbolicLink() || !stat.isDirectory()) throw new Error(`Unsafe economy store directory: ${path}`);
}
function safeRead(path: string): Buffer {
  if (!lstatSync(path).isFile()) throw new Error('Unsafe economy store file');
  // A replaced FIFO must not block before the descriptor type can be checked.
  const fd = openSync(path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0) | (constants.O_NONBLOCK ?? 0));
  try {
    const stat = fstatSync(fd);
    if (!stat.isFile()) throw new Error('Unsafe economy store file');
    if (stat.size > ECONOMY_MAX_BYTES) throw new Error('Economy object exceeds byte limit');
    return readFileSync(fd);
  } finally { closeSync(fd); }
}

/** Select diagnostics once; resizing only renders bounded excerpts. Indices use UTF-16 units. */
function diagnosticPreview(content: string, diagnostics: boolean): (size: number) => string {
  const hits: number[] = [];
  if (diagnostics) {
    const pattern = /\b(?:error|failed|failure|fatal|exception|panic|not ok)\b/gi;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(content)) !== null) {
      if (hits.length < 2) hits.push(match.index);
      else hits[1] = match.index;
    }
  }
  return (size: number): string => {
    if (content.length <= size) return content;
    if (size === 0) return '[preview omitted]';
    const edge = Math.floor(size / (hits.length ? 4 : 2));
    const ranges: Array<[number, number]> = [[0, edge], [content.length - edge, content.length]];
    const quota = Math.floor((size - edge * 2) / Math.max(1, hits.length));
    for (const hit of hits) {
      const line = content.lastIndexOf('\n', hit - 1) + 1;
      const previous = content.lastIndexOf('\n', Math.max(0, line - 2)) + 1;
      const next = content.indexOf('\n', hit);
      const following = next < 0 ? -1 : content.indexOf('\n', next + 1);
      const end = following < 0 ? content.length : following + 1;
      const start = Math.max(previous, hit - Math.floor(quota / 3));
      ranges.push([start, Math.min(end, start + quota)]);
    }
    ranges.sort((a, b) => a[0] - b[0]);
    let cursor = 0; let result = '';
    for (const [start, end] of ranges) {
      if (start > cursor) result += `\n[${start - cursor} UTF-16 units omitted]\n`;
      if (end > cursor) { result += content.slice(Math.max(cursor, start), end); cursor = end; }
    }
    if (cursor < content.length) result += `\n[${content.length - cursor} UTF-16 units omitted]`;
    return result;
  };
}

/** Local payload accounting only. All offsets are byte offsets, end exclusive. */
export class Economy {
  readonly root: string;
  private readonly store: string;
  constructor(repo: string) { this.root = resolve(repo); this.store = join(this.root, '.julius', 'economy'); }
  private initialize(): void {
    safeDirectory(join(this.root, '.julius')); safeDirectory(this.store);
    safeDirectory(join(this.store, 'objects')); safeDirectory(join(this.store, 'events'));
  }
  private save(bytes: Buffer): string {
    this.initialize();
    if (bytes.length > ECONOMY_MAX_BYTES) throw new Error(`Capture exceeds ${ECONOMY_MAX_BYTES} byte limit; nothing captured`);
    const hash = digest(bytes); const path = join(this.store, 'objects', hash);
    const pending = join(this.store, 'objects', `${randomUUID()}.tmp`);
    writeFileSync(pending, bytes, { flag: 'wx', mode: 0o600 });
    try {
      try { linkSync(pending, path); }
      catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error;
        if (digest(safeRead(path)) !== hash) throw new Error('Corrupt economy object');
      }
    } finally { unlinkSync(pending); }
    return `sha256:${hash}`;
  }
  private record(rawTokens: number | null, deliveredTokens: number | null): void {
    this.initialize();
    const id = randomUUID(); const path = join(this.store, 'events', id);
    writeFileSync(path + '.tmp', JSON.stringify({ rawTokens, deliveredTokens }), { flag: 'wx', mode: 0o600 });
    renameSync(path + '.tmp', path + '.json');
  }
  private render(bytes: Buffer, handle: string, budget: number, start = 0, total = bytes.length): EconomyResult {
    const render = (part: Buffer) => JSON.stringify({ handle, start, end: start + part.length, totalBytes: total,
      omittedBytes: total - part.length, ...representation(part), recover: `julius read ${handle} --raw` });
    let size = Math.min(bytes.length, budget * 3);
    let part = bytes.subarray(0, size); let text = render(part);
    while ((countPayloadTokens(text) ?? Infinity) > budget && size > 0) { size = Math.floor(size / 2); part = bytes.subarray(0, size); text = render(part); }
    if (economyTokens(text) > budget) throw new Error(`budget too small: minimum envelope requires ${economyTokens(render(Buffer.alloc(0)))} cl100k_base tokens`);
    return { text, handle, bytes: part, omittedBytes: total - part.length };
  }
  async capture(input: string | Uint8Array, options: CaptureOptions): Promise<EconomyResult> {
    budgetCheck(options.budget);
    const bytes = Buffer.from(input);
    if (bytes.length > ECONOMY_MAX_BYTES) throw new Error(`Capture exceeds ${ECONOMY_MAX_BYTES} byte limit; nothing captured`);
    const raw = representation(bytes); const rawTokens = countPayloadTokens(raw.content);
    let result: EconomyResult;
    if (raw.format === 'utf8' && rawTokens !== null && rawTokens <= options.budget) result = { text: raw.content, handle: null, bytes, omittedBytes: 0 };
    else { const handle = this.save(bytes); result = this.render(bytes, handle, options.budget); }
    this.record(rawTokens, economyTokens(result.text)); return result;
  }
  async read(handle: string, options: ReadOptions): Promise<EconomyResult> {
    budgetCheck(options.budget);
    if (!/^sha256:[a-f0-9]{64}$/.test(handle)) throw new Error('Invalid economy handle');
    this.initialize();
    let bytes: Buffer;
    try { bytes = safeRead(join(this.store, 'objects', handle.slice(7))); }
    catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') throw new Error('Economy handle missing or expired'); throw error; }
    if (digest(bytes) !== handle.slice(7)) throw new Error('Corrupt economy object: digest mismatch');
    let start = options.start ?? 0; const end = options.end ?? bytes.length;
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 0 || end < start || end > bytes.length) throw new Error('Invalid byte range');
    if (options.search !== undefined) {
      if (!options.search.length) throw new Error('search must not be empty');
      const found = bytes.subarray(start, end).indexOf(Buffer.from(options.search));
      if (found < 0) throw new Error('Search text not found');
      start += found;
    }
    const selected = bytes.subarray(start, end);
    const result = options.raw
      ? { text: representation(selected).content, bytes: selected, handle, omittedBytes: bytes.length - selected.length }
      : this.render(selected, handle, options.budget, start, bytes.length);
    this.record(0, countPayloadTokens(result.text)); return result;
  }
  async run(argv: string[], options: RunOptions): Promise<RunResult> {
    budgetCheck(options.budget);
    if (!Array.isArray(argv) || !argv.length || argv.some(arg => typeof arg !== 'string' || arg.includes('\0')) || !argv[0]) throw new Error('Command requires a nonempty argv without NUL bytes');
    const maxBytes = options.maxBytes ?? ECONOMY_MAX_BYTES;
    const timeoutMs = options.timeoutMs ?? 300000;
    if (!Number.isSafeInteger(maxBytes) || maxBytes < 1 || maxBytes > ECONOMY_MAX_BYTES) throw new Error(`maxBytes must be from 1 to ${ECONOMY_MAX_BYTES}`);
    if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 300000) throw new Error('timeoutMs must be from 1 to 300000');
    const shell = (status: number | null, signal: NodeJS.Signals | null, stdoutHandle: string, stderrHandle: string, limit: 'bytes' | 'timeout' | null, stdout: string, stderr: string) =>
      JSON.stringify({ status, signal, complete: limit === null, limit, stdoutHandle, stderrHandle, stdout, stderr, recover: 'julius read <handle> --raw; handles recover captured bytes only' });
    // Each digest byte can occupy a token: reserve worst-case handle space before executing.
    const minimum = 300;
    if (options.budget < minimum) throw new Error(`Command budget minimum is ${minimum} cl100k_base tokens`);
    this.initialize();
    const captured = await new Promise<{ stdout: Buffer; stderr: Buffer; status: number | null; signal: NodeJS.Signals | null; limit: 'bytes' | 'timeout' | null }>((resolveRun, reject) => {
      const child = spawn(argv[0]!, argv.slice(1), { cwd: this.root, shell: false, stdio: ['ignore', 'pipe', 'pipe'] });
      const out: Buffer[] = []; const err: Buffer[] = []; let size = 0; let limit: 'bytes' | 'timeout' | null = null;
      const stop = (reason: 'bytes' | 'timeout') => { if (limit === null) { limit = reason; child.kill('SIGKILL'); child.stdout.destroy(); child.stderr.destroy(); } };
      const timer = setTimeout(() => stop('timeout'), timeoutMs);
      const collect = (parts: Buffer[], data: Buffer) => {
        const remaining = maxBytes - size; const accepted = data.subarray(0, remaining);
        parts.push(accepted); size += accepted.length;
        if (accepted.length < data.length) stop('bytes');
      };
      child.stdout.on('data', (data: Buffer) => collect(out, data));
      child.stderr.on('data', (data: Buffer) => collect(err, data));
      child.on('error', error => { clearTimeout(timer); reject(error); });
      child.on('close', (status, signal) => { clearTimeout(timer); resolveRun({ stdout: Buffer.concat(out), stderr: Buffer.concat(err), status, signal, limit }); });
    });
    const stdoutHandle = this.save(captured.stdout); const stderrHandle = this.save(captured.stderr);
    const out = representation(captured.stdout); const err = representation(captured.stderr);
    const outPreview = diagnosticPreview(out.content, out.format === 'utf8');
    const errPreview = diagnosticPreview(err.content, err.format === 'utf8');
    let previewSize = Math.min(options.budget * 2, 2048);
    const render = () => shell(captured.status, captured.signal, stdoutHandle, stderrHandle, captured.limit,
      `${out.format}: ${outPreview(previewSize)}`,
      `${err.format}: ${errPreview(previewSize)}`);
    let text = render();
    while ((countPayloadTokens(text) ?? Infinity) > options.budget && previewSize > 0) { previewSize = Math.floor(previewSize / 2); text = render(); }
    if (economyTokens(text) > options.budget) throw new Error('Command envelope exceeds budget; captured objects remain available');
    const outCount = countPayloadTokens(out.content); const errCount = countPayloadTokens(err.content);
    this.record(outCount === null || errCount === null ? null : outCount + errCount, economyTokens(text));
    return { text, status: captured.status, signal: captured.signal, stdoutHandle, stderrHandle, complete: captured.limit === null, limit: captured.limit };
  }
  /** Explicit retention boundary. Stop active captures before clearing. */
  async clear(): Promise<void> {
    this.initialize();
    const retired = join(this.root, '.julius', `economy-clearing-${randomUUID()}`);
    // Detach this generation atomically. Data created in a new store afterwards
    // is outside the removal target; failures are surfaced rather than hidden.
    renameSync(this.store, retired);
    rmSync(retired, { recursive: true });
  }
  async stats(): Promise<EconomyStats> {
    this.initialize(); const entries = readdirSync(join(this.store, 'events')).filter(name => /^[a-f0-9-]+\.json$/.test(name));
    if (entries.length > 100000) throw new Error('Economy ledger exceeds 100000 events; archive it before continuing');
    let rawTokens = 0; let deliveredTokens = 0; let rawUncountedEvents = 0; let deliveredUncountedEvents = 0; let uncountedEvents = 0;
    for (const entry of entries) {
      const event = JSON.parse(safeRead(join(this.store, 'events', entry)).toString('utf8'));
      if ((event.rawTokens !== null && (!Number.isSafeInteger(event.rawTokens) || event.rawTokens < 0)) || (event.deliveredTokens !== null && (!Number.isSafeInteger(event.deliveredTokens) || event.deliveredTokens < 0))) throw new Error('Corrupt economy ledger event');
      if (event.rawTokens === null) rawUncountedEvents++; else rawTokens += event.rawTokens;
      if (event.deliveredTokens === null) deliveredUncountedEvents++; else deliveredTokens += event.deliveredTokens;
      if (event.rawTokens === null || event.deliveredTokens === null) uncountedEvents++;
    }
    return { encoding: ECONOMY_ENCODING, rawTokens: rawUncountedEvents ? null : rawTokens, deliveredTokens: deliveredUncountedEvents ? null : deliveredTokens,
      savedTokens: uncountedEvents ? null : rawTokens - deliveredTokens, events: entries.length,
      accountedEvents: entries.length - uncountedEvents, uncountedEvents, rawUncountedEvents, deliveredUncountedEvents,
      method: 'Exact offline cl100k_base where counted; unknown for whitespace or non-whitespace runs over 4096 UTF-16 units. Unknown totals are null, never partial sums.', 
      scope: 'Captured payloads minus rendered deliveries; binary uses base64 tokens. Excludes protocol framing, API metadata, schemas, user requests and stats. Not provider usage or invoice savings.' };
  }
}
