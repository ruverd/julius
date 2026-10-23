import { spawn } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { mkdirSync, lstatSync, readFileSync, writeFileSync, readdirSync, renameSync, linkSync, unlinkSync, openSync, closeSync, fstatSync, rmSync, constants } from 'node:fs';
import { resolve, join } from 'node:path';
import { get_encoding } from 'tiktoken';
import { completeHeader, scanLiterals, growSlice, lineHits, utf8SafeEnd, type DeliveryChoice } from './delivery.js';

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
export interface CaptureOptions { budget: number; transport?: 'mcp'; preview?: (handle: string) => string }
export interface ReadOptions extends Omit<CaptureOptions, 'budget'> { budget: number | null; start?: number; end?: number; search?: string; raw?: boolean }
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
  private render(bytes: Buffer, handle: string, budget: number, start = 0, total = bytes.length, transport?: 'mcp', label?: DeliveryChoice['label']): EconomyResult {
    const render = (part: Buffer) => {
      const end = start + part.length;
      const next = transport === 'mcp' && end < total ? { start: end, end: total } : undefined;
      return JSON.stringify({
        ...(label ? { delivery: label } : {}),
        handle, start, end, totalBytes: total, omittedBytes: total - part.length, ...representation(part),
        recover: transport === 'mcp' ? { operation: 'context.read', args: { handle }, instruction: 'Use julius_call with search or byte ranges.' } : `julius read ${handle} --raw`,
        ...(next ? { next } : {}),
      });
    };
    const utf8 = representation(bytes).format === 'utf8';
    const boundary = (size: number) => utf8 ? utf8SafeEnd(bytes, size) : size;
    let size = boundary(Math.min(bytes.length, budget * 3));
    let part = bytes.subarray(0, size); let text = render(part);
    while ((countPayloadTokens(text) ?? Infinity) > budget && size > 0) { size = boundary(Math.floor(size / 2)); part = bytes.subarray(0, size); text = render(part); }
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
    else {
      const handle = this.save(bytes);
      const selected = options.preview?.(handle);
      const tokens = selected ? countPayloadTokens(selected) : null;
      result = selected && tokens !== null && tokens <= options.budget
        ? { text: selected, handle, bytes: Buffer.from(selected), omittedBytes: bytes.length }
        : this.render(bytes, handle, options.budget, 0, bytes.length, options.transport);
    }
    this.record(rawTokens, economyTokens(result.text)); return result;
  }
  async read(handle: string, options: ReadOptions): Promise<EconomyResult> {
    if (options.budget !== null) budgetCheck(options.budget);
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
    const shown = representation(selected);
    const result = options.raw
      ? { text: shown.content, bytes: selected, handle, omittedBytes: bytes.length - selected.length }
      : options.budget === null
        ? { text: JSON.stringify({ delivery: 'complete', handle, start, end, totalBytes: bytes.length, omittedBytes: bytes.length - selected.length, format: shown.format }) + '\n' + shown.content,
          bytes: selected, handle, omittedBytes: bytes.length - selected.length }
        : this.render(selected, handle, options.budget, start, bytes.length, options.transport);
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
  hold(input: string | Uint8Array): string {
    const bytes = Buffer.from(input);
    if (bytes.length > ECONOMY_MAX_BYTES) throw new Error(`Capture exceeds ${ECONOMY_MAX_BYTES} byte limit; nothing captured`);
    return this.save(bytes);
  }

  recordDelivery(rawTokens: number | null, deliveredTokens: number | null): void {
    this.record(rawTokens, deliveredTokens);
  }

  async present(input: string | Uint8Array, choice: DeliveryChoice, transport?: 'mcp'): Promise<EconomyResult> {
    if (choice.budget !== null) budgetCheck(choice.budget);
    const bytes = Buffer.from(input);
    if (bytes.length > ECONOMY_MAX_BYTES) throw new Error(`Capture exceeds ${ECONOMY_MAX_BYTES} byte limit; nothing captured`);
    const raw = representation(bytes);
    const rawTokens = countPayloadTokens(raw.content);
    const recover = (handle: string) => transport === 'mcp'
      ? { operation: 'context.read', args: { handle }, instruction: 'Use julius_call with search or byte ranges.' }
      : `julius read ${handle} --raw`;
    const bounded = (label: DeliveryChoice['label']) => {
      const budget = choice.budget ?? 1200;
      if (raw.format === 'utf8' && rawTokens !== null && rawTokens <= budget) {
        this.record(rawTokens, rawTokens);
        return { text: raw.content, handle: null, bytes, omittedBytes: 0 };
      }
      const handle = this.save(bytes);
      const result = this.render(bytes, handle, budget, 0, bytes.length, transport, label);
      this.record(rawTokens, economyTokens(result.text));
      return result;
    };
    switch (choice.algorithm) {
      case 'full': {
        const handle = this.save(bytes);
        const format = raw.format === 'base64' ? 'base64' : 'utf8';
        if (rawTokens === null) {
          const text = completeHeader({ handle, totalBytes: bytes.length, omittedBytes: bytes.length, incomplete: true, next: { start: 0, end: bytes.length }, format });
          this.record(null, null);
          return { text, handle, bytes: Buffer.alloc(0), omittedBytes: bytes.length };
        }
        const renderAt = (end: number) => {
          const prefix = bytes.subarray(0, end);
          const shown = representation(prefix);
          const incomplete = end < bytes.length;
          return `${completeHeader({ handle, totalBytes: bytes.length, omittedBytes: bytes.length - prefix.length, incomplete, next: incomplete ? { start: end, end: bytes.length } : null, format: shown.format === 'base64' ? 'base64' : 'utf8' })}\n${shown.content}`;
        };
        if (choice.budget === null) {
          const text = renderAt(bytes.length);
          this.record(rawTokens, economyTokens(text));
          return { text, handle, bytes, omittedBytes: 0 };
        }
        const empty = renderAt(0);
        if (economyTokens(empty) > choice.budget) throw new Error(`budget too small: minimum envelope requires ${economyTokens(empty)} cl100k_base tokens`);
        let lo = 0; let hi = bytes.length; let best = 0; let bestText = empty;
        while (lo <= hi) {
          const mid = Math.floor((lo + hi) / 2);
          const end = format === 'utf8' ? utf8SafeEnd(bytes, mid) : mid;
          const text = renderAt(end);
          let tokens = Infinity;
          try { tokens = economyTokens(text); } catch { tokens = Infinity; }
          if (tokens <= choice.budget) { best = end; bestText = text; lo = mid + 1; }
          else hi = mid - 1;
        }
        this.record(rawTokens, economyTokens(bestText));
        return { text: bestText, handle, bytes: bytes.subarray(0, best), omittedBytes: bytes.length - best };
      }
      case 'targeted': {
        const budget = choice.budget ?? 1200;
        if (choice.literals.length === 0) return bounded(choice.label);
        if (raw.format === 'utf8' && rawTokens !== null && rawTokens <= budget) {
          this.record(rawTokens, rawTokens);
          return { text: raw.content, handle: null, bytes, omittedBytes: 0 };
        }
        const handle = this.save(bytes);
        const { hits, count: matchCount } = scanLiterals(bytes, choice.literals);
        const base = { delivery: 'targeted' as const, handle, totalBytes: bytes.length, recover: recover(handle) };
        if (hits.length === 0) {
          const text = JSON.stringify({ ...base, match: false, matchCount: 0, offsets: [], start: 0, end: 0, omittedBytes: bytes.length, content: '', format: 'utf8', next: { start: 0, end: bytes.length } });
          if (economyTokens(text) > budget) throw new Error(`budget too small: minimum envelope requires ${economyTokens(text)} cl100k_base tokens`);
          this.record(rawTokens, economyTokens(text));
          return { text, handle, bytes: Buffer.alloc(0), omittedBytes: bytes.length };
        }
        const offsets = hits.slice(1, 9).map(hit => hit.start);
        const lines = raw.format === 'utf8' ? lineHits(bytes, choice.literals) : [];
        if (lines.length > 0) {
          const renderHits = (count: number) => {
            const shown = lines.slice(0, count);
            const kept = shown.reduce((sum, hit) => sum + (hit.end - hit.start), 0);
            const nextHit = lines[count];
            const next = nextHit ? { start: nextHit.start, end: bytes.length } : null;
            return JSON.stringify({
              ...base,
              match: true,
              matchCount: lines.length,
              offsets,
              start: shown[0]!.start,
              end: shown[shown.length - 1]!.end,
              omittedBytes: bytes.length - kept,
              content: shown.map(hit => hit.text).join('\n'),
              hits: shown.map(({ line, text }) => ({ line, text })),
              format: 'utf8',
              ...(next ? { next } : {}),
            });
          };
          let count = 0;
          let text = '';
          for (let next = 1; next <= lines.length; next++) {
            const candidate = renderHits(next);
            let tokens = Infinity;
            try { tokens = economyTokens(candidate); } catch { tokens = Infinity; }
            if (tokens > budget) break;
            count = next;
            text = candidate;
          }
          if (count === 0) {
            const missed = JSON.stringify({ ...base, match: true, anchorOmitted: true, matchCount: lines.length, offsets, start: lines[0]!.start, end: lines[0]!.start, omittedBytes: bytes.length, content: '', hits: [], format: 'utf8', next: { start: lines[0]!.start, end: bytes.length } });
            if (economyTokens(missed) > budget) throw new Error(`budget too small: minimum envelope requires ${economyTokens(missed)} cl100k_base tokens`);
            this.record(rawTokens, economyTokens(missed));
            return { text: missed, handle, bytes: Buffer.alloc(0), omittedBytes: bytes.length };
          }
          this.record(rawTokens, economyTokens(text));
          const shown = lines.slice(0, count);
          const kept = shown.reduce((sum, hit) => sum + (hit.end - hit.start), 0);
          return { text, handle, bytes: Buffer.concat(shown.map(hit => bytes.subarray(hit.start, hit.end))), omittedBytes: bytes.length - kept };
        }
        const rendered = (start: number, end: number) => {
          const slice = bytes.subarray(start, end);
          const shown = representation(slice);
          const next = end < bytes.length ? { start: end, end: bytes.length } : null;
          return JSON.stringify({ ...base, match: true, matchCount, offsets, start, end, omittedBytes: bytes.length - slice.length, content: shown.content, format: shown.format, ...(next ? { next } : {}) });
        };
        const grown = growSlice(bytes, hits[0]!.start, hits[0]!.end, (start, end) => {
          try { return economyTokens(rendered(start, end)) <= budget; } catch { return false; }
        });
        if (grown === null) {
          const text = JSON.stringify({ ...base, match: true, anchorOmitted: true, matchCount, offsets, start: hits[0]!.start, end: hits[0]!.start, omittedBytes: bytes.length, content: '', format: 'utf8', next: { start: hits[0]!.start, end: bytes.length } });
          if (economyTokens(text) > budget) throw new Error(`budget too small: minimum envelope requires ${economyTokens(text)} cl100k_base tokens`);
          this.record(rawTokens, economyTokens(text));
          return { text, handle, bytes: Buffer.alloc(0), omittedBytes: bytes.length };
        }
        const text = rendered(grown.start, grown.end);
        this.record(rawTokens, economyTokens(text));
        return { text, handle, bytes: bytes.subarray(grown.start, grown.end), omittedBytes: bytes.length - (grown.end - grown.start) };
      }
      case 'fixed':
        return bounded(choice.label);
      default: {
        const never: never = choice.algorithm;
        throw new Error(`Unknown delivery algorithm: ${String(never)}`);
      }
    }
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
