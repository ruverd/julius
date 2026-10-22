export interface DeliveryChoice {
  algorithm: 'full' | 'targeted' | 'fixed';
  label: 'complete' | 'targeted' | 'fixed';
  budget: number | null;
  literals: string[];
}

const named = ['query', 'pattern', 'symbol', 'file', 'path'] as const;

function text(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

export function selectorLiterals(focus: string | undefined, args: Record<string, unknown>): string[] {
  const focused = text(focus);
  if (focused) return [focused];
  for (const key of named) {
    const value = text(args[key]);
    if (value) return [value];
  }
  if (Array.isArray(args.paths)) {
    const paths = args.paths.filter((item): item is string => typeof item === 'string' && item.length > 0);
    if (paths.length > 0) return paths;
  }
  return [];
}

export function selectDelivery(input: { delivery?: string; focus?: string; budget?: number; args: Record<string, unknown> }): DeliveryChoice {
  if (input.delivery !== undefined && input.delivery !== 'selective' && input.delivery !== 'complete') {
    throw new Error('delivery must be selective or complete');
  }
  if (input.delivery === 'complete') {
    return { algorithm: 'full', label: 'complete', budget: input.budget === undefined ? null : input.budget, literals: [] };
  }
  const literals = selectorLiterals(input.focus, input.args);
  if (input.delivery === 'selective' || literals.length > 0) {
    return { algorithm: literals.length > 0 ? 'targeted' : 'fixed', label: 'targeted', budget: input.budget ?? 1200, literals };
  }
  return { algorithm: 'fixed', label: 'fixed', budget: input.budget ?? 1200, literals: [] };
}

export function utf8SafeEnd(bytes: Buffer, end: number): number {
  let n = Math.min(bytes.length, Math.max(0, end));
  while (n > 0 && n < bytes.length && (bytes[n]! & 0xc0) === 0x80) n--;
  return n;
}

function prevBoundary(bytes: Buffer, index: number): number {
  let i = index - 1;
  while (i > 0 && (bytes[i]! & 0xc0) === 0x80) i--;
  return Math.max(0, i);
}

function nextBoundary(bytes: Buffer, index: number): number {
  if (index >= bytes.length) return bytes.length;
  const lead = bytes[index]!;
  const width = lead < 0x80 ? 1 : (lead & 0xe0) === 0xc0 ? 2 : (lead & 0xf0) === 0xe0 ? 3 : (lead & 0xf8) === 0xf0 ? 4 : 1;
  return Math.min(bytes.length, index + width);
}

export function findLiterals(bytes: Buffer, literals: string[]): Array<{ start: number; end: number }> {
  const found: Array<{ start: number; end: number; order: number }> = [];
  literals.forEach((literal, order) => {
    const pattern = Buffer.from(literal);
    if (pattern.length === 0) return;
    let from = 0;
    while (from <= bytes.length - pattern.length) {
      const at = bytes.subarray(from).indexOf(pattern);
      if (at < 0) break;
      const start = from + at;
      found.push({ start, end: start + pattern.length, order });
      from = start + pattern.length;
    }
  });
  found.sort((a, b) => a.start - b.start || a.order - b.order);
  const kept: Array<{ start: number; end: number }> = [];
  let cursor = 0;
  for (const hit of found) {
    if (hit.start < cursor) continue;
    kept.push({ start: hit.start, end: hit.end });
    cursor = hit.end;
  }
  return kept;
}

export function growSlice(bytes: Buffer, anchorStart: number, anchorEnd: number, fits: (start: number, end: number) => boolean): { start: number; end: number } | null {
  if (!fits(anchorStart, anchorEnd)) return null;
  let start = anchorStart;
  let end = anchorEnd;
  const lineAt = bytes.lastIndexOf(0x0a, Math.max(0, start - 1));
  const lineStart = lineAt < 0 ? 0 : lineAt + 1;
  const breakAt = bytes.indexOf(0x0a, end);
  const lineEnd = breakAt < 0 ? bytes.length : breakAt + 1;
  if ((lineStart !== start || lineEnd !== end) && fits(lineStart, lineEnd)) {
    start = lineStart;
    end = lineEnd;
  }
  let grew = true;
  while (grew) {
    grew = false;
    if (start > 0) {
      const next = prevBoundary(bytes, start);
      if (next < start && fits(next, end)) { start = next; grew = true; }
    }
    if (end < bytes.length) {
      const next = nextBoundary(bytes, end);
      if (next > end && fits(start, next)) { end = next; grew = true; }
    }
  }
  return { start, end };
}

export function completeHeader(fields: { handle: string; totalBytes: number; omittedBytes: number; incomplete: boolean; next: { start: number; end: number } | null; format: 'utf8' | 'base64' }): string {
  return JSON.stringify({
    delivery: 'complete',
    handle: fields.handle,
    totalBytes: fields.totalBytes,
    omittedBytes: fields.omittedBytes,
    incomplete: fields.incomplete,
    next: fields.next,
    format: fields.format,
  });
}
