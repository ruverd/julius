# Selective delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Choose full, targeted, or fixed delivery for a large local result, and reject the change unless an offline probe spends fewer tokens on specific facts and on complete delivery than the fixed preview.

**Architecture:** `selectDelivery` is a pure function. `Economy.present` renders the three envelopes and stores bytes in the existing `.julius/economy` object store. Compact `julius_call` passes `delivery` and `focus`. Investigation reports keep `coverage` and `unknowns` while filtering evidence. A frozen one-repo probe compares always-complete, fixed, and policy arms.

**Tech Stack:** Node.js 20+, TypeScript, npm, `node:test` via `node --import tsx --test`, existing `cl100k_base` counter in `src/economy/index.ts`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-10-22-selective-delivery-design.md`.
- Node.js 20 or later, TypeScript, npm. English identifiers, docs, and commit messages.
- No new dependency, network call, telemetry, or model.
- Do not edit `scripts/experiments/local-comparison-tasks.json`.
- Public `delivery` values are `selective` and `complete`. `fixed` is a harness algorithm only.
- `budget` on `julius_call` stays an integer from 256 through 16000. Omitted `budget` is not the same as explicit `1200`.
- Omitted budget for `targeted` and `fixed` means 1200 `cl100k_base` tokens. Omitted budget for `delivery: "complete"` means one uncapped body, still subject to the existing 8 MB capture ceiling.
- Unknown token counts stay `null`. Negative savings stay visible. A recovery read still records raw tokens as 0.
- Do not add comments.
- `julius read` and the inherited full tool list stay unchanged.
- `advance-offline-only` does not authorize a 400-token default or a billing claim.

## File structure

- Create `src/economy/delivery.ts`. Pure policy, literal search, window growth, UTF-8 truncation, complete header. No tokenizer import.
- Modify `src/economy/index.ts`. `Economy.present`, `Economy.hold`, `Economy.recordDelivery`, and MCP `next` on `read`.
- Modify `src/mcp/compact.ts`. Schema fields and the call path.
- Modify `src/investigation/index.ts`. Evidence filter and full-report framing.
- Modify `src/hosts/investigation-instructions.ts`, `README.md`, `docs/investigations.md`.
- Create `test/delivery.test.ts`. Unit coverage for policy, envelopes, compact calls, and investigation.
- Create `scripts/experiments/delivery-policy-tasks.json` and `scripts/experiments/delivery-policy.ts`.
- Create `test/delivery-policy.test.ts`. Decision function and the offline probe.

---

### Task 1: Delivery choice

**Files:**
- Create: `src/economy/delivery.ts`
- Test: `test/delivery.test.ts`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `export interface DeliveryChoice { algorithm: 'full' | 'targeted' | 'fixed'; label: 'complete' | 'targeted' | 'fixed'; budget: number | null; literals: string[] }`
  - `export function selectorLiterals(focus: string | undefined, args: Record<string, unknown>): string[]`
  - `export function selectDelivery(input: { delivery?: string; focus?: string; budget?: number; args: Record<string, unknown> }): DeliveryChoice`

- [ ] **Step 1: Write the failing test**

Create `test/delivery.test.ts`:

```ts
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { selectDelivery, selectorLiterals } from '../src/economy/delivery.js';

test('selector literals keep precedence and do not fall through', () => {
  assert.deepEqual(selectorLiterals('NEEDLE', { query: 'other', paths: ['a.ts'] }), ['NEEDLE']);
  assert.deepEqual(selectorLiterals(undefined, { query: 'missing', paths: ['a.ts'] }), ['missing']);
  assert.deepEqual(selectorLiterals(undefined, { pattern: 'pat' }), ['pat']);
  assert.deepEqual(selectorLiterals(undefined, { symbol: 'hello' }), ['hello']);
  assert.deepEqual(selectorLiterals(undefined, { file: 'src/a.ts' }), ['src/a.ts']);
  assert.deepEqual(selectorLiterals(undefined, { path: 'src/a.ts' }), ['src/a.ts']);
  assert.deepEqual(selectorLiterals(undefined, { paths: ['src/a.ts', 'src/b.ts'] }), ['src/a.ts', 'src/b.ts']);
  assert.deepEqual(selectorLiterals(undefined, { in: 'src', depth: 2, limit: 10, max_dirs: 4, content: 'body', recipe: 'change-impact' }), []);
});

test('selectDelivery distinguishes omitted budget from an explicit cap', () => {
  assert.deepEqual(selectDelivery({ delivery: 'complete', focus: 'NEEDLE', args: { query: 'q' } }), {
    algorithm: 'full', label: 'complete', budget: null, literals: [],
  });
  assert.deepEqual(selectDelivery({ delivery: 'complete', budget: 1200, args: {} }), {
    algorithm: 'full', label: 'complete', budget: 1200, literals: [],
  });
  assert.deepEqual(selectDelivery({ delivery: 'selective', args: {} }), {
    algorithm: 'fixed', label: 'targeted', budget: 1200, literals: [],
  });
  assert.deepEqual(selectDelivery({ args: { symbol: 'hello' } }), {
    algorithm: 'targeted', label: 'targeted', budget: 1200, literals: ['hello'],
  });
  assert.deepEqual(selectDelivery({ focus: 'NEEDLE', budget: 400, args: {} }), {
    algorithm: 'targeted', label: 'targeted', budget: 400, literals: ['NEEDLE'],
  });
  assert.deepEqual(selectDelivery({ args: { in: 'src' } }), {
    algorithm: 'fixed', label: 'fixed', budget: 1200, literals: [],
  });
  assert.throws(() => selectDelivery({ delivery: 'fixed', args: {} }), /delivery must be selective or complete/);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --import tsx --test test/delivery.test.ts`

Expected: FAIL because `../src/economy/delivery.js` does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `src/economy/delivery.ts`:

```ts
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --import tsx --test test/delivery.test.ts`

Expected: PASS, 2 tests.

- [ ] **Step 5: Commit**

```bash
git add src/economy/delivery.ts test/delivery.test.ts
git commit -m "$(cat <<'EOF'
feat: choose full, targeted, or fixed delivery from the call

EOF
)"
```

---

### Task 2: Window helpers

**Files:**
- Modify: `src/economy/delivery.ts`
- Test: `test/delivery.test.ts`

**Interfaces:**
- Consumes: `DeliveryChoice` from Task 1
- Produces:
  - `export function utf8SafeEnd(bytes: Buffer, end: number): number`
  - `export function findLiterals(bytes: Buffer, literals: string[]): Array<{ start: number; end: number }>`
  - `export function growSlice(bytes: Buffer, anchorStart: number, anchorEnd: number, fits: (start: number, end: number) => boolean): { start: number; end: number } | null`
  - `export function completeHeader(fields: { handle: string; totalBytes: number; omittedBytes: number; incomplete: boolean; next: { start: number; end: number } | null; format: 'utf8' | 'base64' }): string`

- [ ] **Step 1: Write the failing test**

Add `completeHeader`, `findLiterals`, `growSlice`, and `utf8SafeEnd` to the existing import from `../src/economy/delivery.js`. Then append:

```ts
test('utf-8 truncation lands on code point boundaries', () => {
  const bytes = Buffer.from('ação🙂');
  assert.equal(utf8SafeEnd(bytes, 0), 0);
  assert.equal(utf8SafeEnd(bytes, 1), 0);
  assert.equal(utf8SafeEnd(bytes, 2), 2);
  assert.equal(utf8SafeEnd(bytes, bytes.length), bytes.length);
});

test('literal search is non-overlapping and path order breaks ties', () => {
  const bytes = Buffer.from('alpha alpha beta');
  assert.deepEqual(findLiterals(bytes, ['alpha']), [{ start: 0, end: 5 }, { start: 6, end: 11 }]);
  const tie = Buffer.from('ab');
  assert.deepEqual(findLiterals(tie, ['b', 'ab']), [{ start: 0, end: 2 }]);
});

test('window growth keeps the anchor and stops when the callback rejects', () => {
  const bytes = Buffer.from('head\nTARGET\ntail');
  const anchor = findLiterals(bytes, ['TARGET'])[0]!;
  const wide = growSlice(bytes, anchor.start, anchor.end, () => true);
  assert.deepEqual(wide, { start: 0, end: bytes.length });
  const tight = growSlice(bytes, anchor.start, anchor.end, (start, end) => end - start <= 'TARGET'.length);
  assert.deepEqual(tight, { start: anchor.start, end: anchor.end });
  assert.equal(growSlice(bytes, anchor.start, anchor.end, () => false), null);
});

test('complete header is one JSON line with stable keys', () => {
  assert.equal(completeHeader({
    handle: 'sha256:' + 'a'.repeat(64), totalBytes: 4, omittedBytes: 0, incomplete: false, next: null, format: 'utf8',
  }), '{"delivery":"complete","handle":"sha256:' + 'a'.repeat(64) + '","totalBytes":4,"omittedBytes":0,"incomplete":false,"next":null,"format":"utf8"}');
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --import tsx --test test/delivery.test.ts`

Expected: FAIL because `utf8SafeEnd` is not exported.

- [ ] **Step 3: Write minimal implementation**

Append to `src/economy/delivery.ts`:

```ts
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --import tsx --test test/delivery.test.ts`

Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add src/economy/delivery.ts test/delivery.test.ts
git commit -m "$(cat <<'EOF'
feat: locate delivery windows on UTF-8 boundaries

EOF
)"
```

---

### Task 3: Economy envelopes

**Files:**
- Modify: `src/economy/index.ts`
- Test: `test/delivery.test.ts`

**Interfaces:**
- Consumes: `DeliveryChoice`, `completeHeader`, `findLiterals`, `growSlice`, `utf8SafeEnd`
- Produces:
  - `Economy.present(input: string | Uint8Array, choice: DeliveryChoice, transport?: 'mcp'): Promise<EconomyResult>`
  - `Economy.hold(input: string | Uint8Array): string`
  - `Economy.recordDelivery(rawTokens: number | null, deliveredTokens: number | null): void`
  - MCP `read` JSON gains `next` when the delivered slice stops before `totalBytes`

- [ ] **Step 1: Write the failing test**

Add the `node:fs`, `node:os`, `node:path`, `Economy`, `economyTokens`, and `DeliveryChoice` imports at the top of `test/delivery.test.ts`. Then append:

```ts
function repo(): string {
  return mkdtempSync(join(tmpdir(), 'delivery-'));
}

test('full delivery writes a header and the verbatim body', async () => {
  const root = repo();
  try {
    const body = 'ação🙂\r\nretry_limit=7';
    const choice: DeliveryChoice = { algorithm: 'full', label: 'complete', budget: null, literals: [] };
    const result = await new Economy(root).present(body, choice, 'mcp');
    const split = result.text.indexOf('\n');
    const header = JSON.parse(result.text.slice(0, split));
    assert.equal(result.text.slice(split + 1), body);
    assert.equal(header.delivery, 'complete');
    assert.equal(header.incomplete, false);
    assert.equal(header.next, null);
    assert.equal(header.handle, result.handle);
    const raw = await new Economy(root).read(header.handle, { budget: 16000, raw: true });
    assert.equal(raw.bytes.toString('utf8'), body);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('an explicit complete budget leaves a contiguous next cursor', async () => {
  const root = repo();
  try {
    const body = 'ação🙂\r\n'.repeat(80);
    const choice: DeliveryChoice = { algorithm: 'full', label: 'complete', budget: 256, literals: [] };
    const economy = new Economy(root);
    const result = await economy.present(body, choice, 'mcp');
    const split = result.text.indexOf('\n');
    const header = JSON.parse(result.text.slice(0, split));
    assert.equal(header.incomplete, true);
    assert.equal(header.next.start, Buffer.byteLength(result.text.slice(split + 1)));
    const chunks = [result.text.slice(split + 1)];
    let start = header.next.start as number;
    let guard = 0;
    while (start < Buffer.byteLength(body)) {
      const read = await economy.read(header.handle, { start, budget: 256, transport: 'mcp' });
      chunks.push(read.bytes.toString('utf8'));
      const parsed = JSON.parse(read.text);
      assert.equal(parsed.start, start);
      start = parsed.next ? parsed.next.start : parsed.end;
      assert.ok(++guard < 20);
    }
    assert.equal(chunks.join(''), body);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('targeted delivery windows the literal and a miss copies no head', async () => {
  const root = repo();
  try {
    const body = `${'head '.repeat(800)}\nTARGET retry_limit=7\n${'tail '.repeat(800)}`;
    const economy = new Economy(root);
    const hit = await economy.present(body, { algorithm: 'targeted', label: 'targeted', budget: 300, literals: ['retry_limit=7'] }, 'mcp');
    const hitBody = JSON.parse(hit.text);
    assert.equal(hitBody.match, true);
    assert.match(hitBody.content, /retry_limit=7/);
    assert.ok(economyTokens(hit.text) <= 300);
    assert.ok(hitBody.offsets.length <= 8);
    const miss = await economy.present(body, { algorithm: 'targeted', label: 'targeted', budget: 1200, literals: ['BENCH_MARKER_MISSING'] }, 'mcp');
    const missBody = JSON.parse(miss.text);
    assert.equal(missBody.match, false);
    assert.equal(missBody.content, '');
    assert.equal(miss.text.includes('head '), false);
    assert.deepEqual(missBody.next, { start: 0, end: Buffer.byteLength(body) });
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('fixed delivery keeps the head and omits a tail fact', async () => {
  const root = repo();
  try {
    const body = `${'word '.repeat(2000)}\nBENCH_MARKER_078: retry_limit=7`;
    const result = await new Economy(root).present(body, { algorithm: 'fixed', label: 'fixed', budget: 1200, literals: [] }, 'mcp');
    assert.equal(result.text.includes('BENCH_MARKER_078'), false);
    const parsed = JSON.parse(result.text);
    assert.equal(parsed.delivery, 'fixed');
    assert.ok(parsed.next.start > 0);
    assert.ok(economyTokens(result.text) <= 1200);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('an uncountable full body stores bytes and records null tokens', async () => {
  const root = repo();
  try {
    const body = 'a'.repeat(4097);
    const economy = new Economy(root);
    const result = await economy.present(body, { algorithm: 'full', label: 'complete', budget: null, literals: [] }, 'mcp');
    assert.equal(result.text.includes('\n'), false);
    const header = JSON.parse(result.text);
    assert.equal(header.incomplete, true);
    assert.deepEqual(header.next, { start: 0, end: body.length });
    const stats = await economy.stats();
    assert.equal(stats.rawTokens, null);
    assert.equal(stats.deliveredTokens, null);
    assert.equal((await economy.read(header.handle, { budget: 16000, raw: true })).bytes.toString('utf8'), body);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --import tsx --test test/delivery.test.ts`

Expected: FAIL because `Economy.present` is not a function.

- [ ] **Step 3: Write minimal implementation**

In `src/economy/index.ts`, import `completeHeader`, `findLiterals`, `growSlice`, `utf8SafeEnd`, and `DeliveryChoice` from `./delivery.js`.

Change `render` so the JSON builder computes `next` from the slice it is rendering, and adds `delivery` only when a label is passed:

```ts
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
  let size = Math.min(bytes.length, budget * 3);
  let part = bytes.subarray(0, size); let text = render(part);
  while ((countPayloadTokens(text) ?? Infinity) > budget && size > 0) { size = Math.floor(size / 2); part = bytes.subarray(0, size); text = render(part); }
  if (economyTokens(text) > budget) throw new Error(`budget too small: minimum envelope requires ${economyTokens(render(Buffer.alloc(0)))} cl100k_base tokens`);
  return { text, handle, bytes: part, omittedBytes: total - part.length };
}
```

Add these methods to `Economy` before `clear`:

```ts
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
      if (raw.format === 'utf8' && rawTokens !== null && rawTokens <= budget && choice.literals.some(literal => raw.content.includes(literal))) {
        this.record(rawTokens, rawTokens);
        return { text: raw.content, handle: null, bytes, omittedBytes: 0 };
      }
      const handle = this.save(bytes);
      const hits = findLiterals(bytes, choice.literals);
      const base = { delivery: 'targeted' as const, handle, totalBytes: bytes.length, recover: recover(handle) };
      if (hits.length === 0) {
        const text = JSON.stringify({ ...base, match: false, matchCount: 0, offsets: [], start: 0, end: 0, omittedBytes: bytes.length, content: '', format: 'utf8', next: { start: 0, end: bytes.length } });
        if (economyTokens(text) > budget) throw new Error(`budget too small: minimum envelope requires ${economyTokens(text)} cl100k_base tokens`);
        this.record(rawTokens, economyTokens(text));
        return { text, handle, bytes: Buffer.alloc(0), omittedBytes: bytes.length };
      }
      const offsets = hits.slice(1, 9).map(hit => hit.start);
      const rendered = (start: number, end: number) => {
        const slice = bytes.subarray(start, end);
        const shown = representation(slice);
        const next = end < bytes.length ? { start: end, end: bytes.length } : null;
        return JSON.stringify({ ...base, match: true, matchCount: hits.length, offsets, start, end, omittedBytes: bytes.length - slice.length, content: shown.content, format: shown.format, ...(next ? { next } : {}) });
      };
      const grown = growSlice(bytes, hits[0]!.start, hits[0]!.end, (start, end) => {
        try { return economyTokens(rendered(start, end)) <= budget; } catch { return false; }
      });
      if (grown === null) {
        const text = JSON.stringify({ ...base, match: false, matchCount: hits.length, offsets, start: hits[0]!.start, end: hits[0]!.start, omittedBytes: bytes.length, content: '', format: 'utf8', next: { start: hits[0]!.start, end: bytes.length } });
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --import tsx --test test/delivery.test.ts test/economy.test.ts`

Expected: PASS. Existing economy tests stay green because `capture` and transport-less `read` keep their current JSON.

- [ ] **Step 5: Commit**

```bash
git add src/economy/index.ts test/delivery.test.ts
git commit -m "$(cat <<'EOF'
feat: render complete and targeted payloads from stored bytes

EOF
)"
```

---

### Task 4: Compact call wiring

**Files:**
- Modify: `src/mcp/compact.ts`
- Test: `test/delivery.test.ts`

**Interfaces:**
- Consumes: `selectDelivery`, `Economy.present`
- Produces: `julius_call` accepts optional `delivery` and `focus`. `callCompact` passes the resulting `DeliveryChoice` into capture, graph results, and investigation. `context.read` stays budget-capped with `choice.budget ?? 1200`. `context.stats` stays a direct JSON response.

- [ ] **Step 1: Write the failing test**

Add `import { callCompact } from '../src/mcp/compact.js';` at the top of `test/delivery.test.ts`. Then append:

```ts
test('compact calls window a focus and return a complete body verbatim', async () => {
  const root = repo();
  try {
    const content = `${'word '.repeat(2000)}\nBENCH_MARKER_078: retry_limit=7`;
    const fixed = await callCompact(root, 'julius_call', { operation: 'context.capture', args: { content } });
    assert.equal(fixed.isError, false, fixed.text);
    assert.equal(fixed.text.includes('BENCH_MARKER_078'), false);
    const focused = await callCompact(root, 'julius_call', { operation: 'context.capture', args: { content }, focus: 'BENCH_MARKER_078: retry_limit=7' });
    assert.equal(focused.isError, false, focused.text);
    assert.match(focused.text, /retry_limit=7/);
    assert.ok(economyTokens(focused.text) <= 1200);
    const complete = await callCompact(root, 'julius_call', { operation: 'context.capture', args: { content }, delivery: 'complete' });
    assert.equal(complete.text.slice(complete.text.indexOf('\n') + 1), content);
    const capped = await callCompact(root, 'julius_call', { operation: 'context.capture', args: { content }, delivery: 'complete', budget: 256 });
    const header = JSON.parse(capped.text.slice(0, capped.text.indexOf('\n')));
    assert.equal(header.incomplete, true);
    assert.ok(header.next);
    const bad = await callCompact(root, 'julius_call', { operation: 'context.capture', args: { content }, delivery: 'fixed' });
    assert.equal(bad.isError, true);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --import tsx --test test/delivery.test.ts`

Expected: FAIL because `delivery: "fixed"` is accepted or `focus` is rejected as an unknown argument, and the complete body is not verbatim.

- [ ] **Step 3: Write minimal implementation**

In `src/mcp/compact.ts`, import `selectDelivery` from `../economy/delivery.js`.

Replace the `julius_call` schema with:

```ts
{ name: 'julius_call', description: 'Run a discovered local investigation or graph/context operation. No shell or arbitrary code execution.', inputSchema: object({ operation: string, args: { type: 'object' }, budget: integer(16000, 256), delivery: { enum: ['selective', 'complete'] }, focus: { type: 'string', minLength: 1, maxLength: 512 } }, ['operation']) },
```

Inside `callCompact`, after `const args = params.args ?? {}` and schema validation of `args`:

```ts
const params = input as { operation?: string; args?: Record<string, unknown>; budget?: number; delivery?: string; focus?: string };
const choice = selectDelivery({ delivery: params.delivery, focus: params.focus, budget: params.budget, args });
```

Replace the operation branches:

```ts
if (operation.name === 'context.capture') return { text: (await economy.present(args.content as string, choice, 'mcp')).text, isError: false };
if (operation.name === 'context.read') return { text: (await economy.read(args.handle as string, { budget: choice.budget ?? 1200, transport: 'mcp', start: args.start as number | undefined, end: args.end as number | undefined, search: args.search as string | undefined })).text, isError: false };
if (operation.name === 'context.stats') return { text: JSON.stringify(await economy.stats()), isError: false };
if (operation.name === 'investigation.execute') return { text: await deliverInvestigation(root, await runInvestigation(root, args as unknown as InvestigationArgs, dir), choice), isError: false };
if (!TOOLS.some(t => t.name === operation.name)) throw new Error('Unsupported graph operation');
await ensureGraph(root, dir);
const result = await callTool(root, operation.name, args, dir);
return { text: (await economy.present(result.text, choice, 'mcp')).text, isError: result.isError };
```

Remove the old `const budget = params.budget ?? 1200` line. `deliverInvestigation` does not accept `DeliveryChoice` until Task 5. For this task only, pass `choice.budget ?? 1200` into the existing numeric `deliverInvestigation` so this task compiles. Task 5 replaces that call with `choice`.

- [ ] **Step 4: Run test to verify it passes**

Run: `node --import tsx --test test/delivery.test.ts test/compact-mcp.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mcp/compact.ts test/delivery.test.ts
git commit -m "$(cat <<'EOF'
feat: accept delivery and focus on compact julius_call

EOF
)"
```

---

### Task 5: Investigation delivery

**Files:**
- Modify: `src/investigation/index.ts`
- Modify: `src/mcp/compact.ts` (`deliverInvestigation(..., choice)`)
- Test: `test/delivery.test.ts`

**Interfaces:**
- Consumes: `DeliveryChoice`, `Economy.hold`, `Economy.recordDelivery`, `Economy.present`, `economyTokens`
- Produces: `deliverInvestigation(root: string, report: InvestigationReport, budgetOrChoice: number | DeliveryChoice): Promise<string>`

- [ ] **Step 1: Write the failing test**

Add `import { deliverInvestigation, type InvestigationReport } from '../src/investigation/index.js';` at the top of `test/delivery.test.ts`. Then append:

```ts
function report(unindexedFiles: number, evidence: InvestigationReport['evidence']): InvestigationReport {
  return {
    version: 1, recipe: 'failure-localization', snapshot: 'snapshot', graphRevision: 'graph',
    coverage: { scope: 'repository source selection', indexedFiles: 1, sourceFiles: 3, unindexedFiles, traversalComplete: true },
    unknowns: ['kept unknown'], evidence, reused: false,
  };
}

test('investigation delivery keeps coverage and withholds unmatched evidence', async () => {
  const root = repo();
  try {
    const evidence = Array.from({ length: 20 }, (_, index) => ({
      id: `a.ts#fn${index}`, path: 'a.ts', span: 'L1-L2', kind: 'function', name: `fn${index}`,
      role: 'dependent' as const, depth: 1, excerpt: `excerpt ${index} ${'pad '.repeat(40)}`, excerptComplete: true,
    }));
    evidence.push({ id: 'b.ts#target', path: 'b.ts', span: 'L3-L4', kind: 'function', name: 'target', role: 'match', depth: 0, excerpt: 'BENCH_MARKER_078: retry_limit=7', excerptComplete: true });
    const full = report(2, evidence);
    const selected = JSON.parse(await deliverInvestigation(root, full, { algorithm: 'targeted', label: 'targeted', budget: 1200, literals: ['BENCH_MARKER_078'] }));
    assert.equal(selected.coverage.unindexedFiles, 2);
    assert.deepEqual(selected.unknowns, ['kept unknown']);
    assert.ok(selected.evidence.every((item: { excerpt: string }) => item.excerpt.includes('BENCH_MARKER_078')));
    assert.equal(selected.evidence.some((item: { path: string }) => item.path === 'vendor/readme.txt'), false);
    const missed = JSON.parse(await deliverInvestigation(root, full, { algorithm: 'targeted', label: 'targeted', budget: 1200, literals: ['BENCH_MARKER_MISSING'] }));
    assert.equal(missed.match, false);
    assert.deepEqual(missed.evidence, []);
    assert.equal(missed.omittedEvidence, evidence.length);
    assert.equal(missed.coverage.unindexedFiles, 2);
    const huge = report(2, [{ id: 'b.ts#target', path: 'b.ts', span: 'L3-L4', kind: 'function', name: 'target', role: 'match', depth: 0, excerpt: `${'pad '.repeat(2000)} BENCH_MARKER_078: retry_limit=7`, excerptComplete: false }]);
    const narrowed = await deliverInvestigation(root, huge, { algorithm: 'targeted', label: 'targeted', budget: 400, literals: ['retry_limit=7'] });
    assert.match(narrowed, /retry_limit=7/);
    assert.ok(economyTokens(narrowed) <= 400);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --import tsx --test test/delivery.test.ts`

Expected: FAIL because `deliverInvestigation` rejects the object argument.

- [ ] **Step 3: Write minimal implementation**

Replace `deliverInvestigation` in `src/investigation/index.ts`. Import `DeliveryChoice` from `../economy/delivery.js`.

```ts
export async function deliverInvestigation(root: string, report: InvestigationReport, budgetOrChoice: number | DeliveryChoice): Promise<string> {
  const choice: DeliveryChoice = typeof budgetOrChoice === 'number'
    ? { algorithm: 'fixed', label: 'fixed', budget: budgetOrChoice, literals: [] }
    : budgetOrChoice;
  const full = JSON.stringify(report);
  const economy = new Economy(root);
  if (choice.algorithm === 'full') return (await economy.present(full, choice, 'mcp')).text;
  const budget = choice.budget ?? 1200;
  const ranked = [...report.evidence].sort((a, b) => Number(b.role !== 'seed') - Number(a.role !== 'seed') || a.depth - b.depth || a.id.localeCompare(b.id));
  const pool = choice.literals.length > 0
    ? ranked.filter(item => choice.literals.some(literal => [item.path, item.name, item.id, item.excerpt].some(field => field.includes(literal))))
    : ranked;
  const recover = (handle: string) => ({ operation: 'context.read', args: { handle }, instruction: 'Search a path or read byte ranges through julius_call; no user command needed.' });
  const handle = economy.hold(full);
  const rawTokens = (() => { try { return economyTokens(full); } catch { return null; } })();
  if (choice.literals.length > 0 && pool.length === 0) {
    const text = JSON.stringify({ ...report, evidence: [], omittedEvidence: ranked.length, match: false, handle, delivery: choice.label, next: { start: 0, end: Buffer.byteLength(full) }, recover: recover(handle) });
    if (economyTokens(text) <= budget) { economy.recordDelivery(rawTokens, economyTokens(text)); return text; }
    return (await economy.present(full, choice, 'mcp')).text;
  }
  let count = pool.length;
  while (count >= 0) {
    const text = JSON.stringify({ ...report, evidence: pool.slice(0, count), omittedEvidence: ranked.length - count, handle, delivery: choice.label, recover: recover(handle) });
    let fits = false;
    try { fits = economyTokens(text) <= budget; } catch { fits = false; }
    if (fits) { economy.recordDelivery(rawTokens, economyTokens(text)); return text; }
    if (count === 0) break;
    count = Math.floor(count / 2);
  }
  if (choice.literals.length > 0) return (await economy.present(full, { ...choice, algorithm: 'targeted' }, 'mcp')).text;
  return (await economy.capture(full, { budget, transport: 'mcp' })).text;
}
```

In `src/mcp/compact.ts`, pass `choice` instead of `choice.budget ?? 1200`:

```ts
if (operation.name === 'investigation.execute') return { text: await deliverInvestigation(root, await runInvestigation(root, args as unknown as InvestigationArgs, dir), choice), isError: false };
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --import tsx --test test/delivery.test.ts test/investigation.test.ts`

Expected: PASS. The existing budget test still sees `omittedEvidence`, `recover.operation === 'context.read'`, and a token count within budget.

- [ ] **Step 5: Commit**

```bash
git add src/investigation/index.ts src/mcp/compact.ts test/delivery.test.ts
git commit -m "$(cat <<'EOF'
feat: filter investigation evidence around the requested literal

EOF
)"
```

---

### Task 6: Agent instructions and docs

**Files:**
- Modify: `src/mcp/compact.ts` (`COMPACT_INSTRUCTIONS`)
- Modify: `src/hosts/investigation-instructions.ts`
- Modify: `README.md` (the Compact MCP budget paragraph)
- Modify: `docs/investigations.md` (the paragraph that starts "Small reports are returned complete.")
- Test: `test/delivery.test.ts`

**Interfaces:**
- Consumes: the public `delivery` and `focus` arguments from Task 4
- Produces: instruction text that tells the agent when to pass a literal, when to pass `delivery: "complete"`, and how to follow `next`

- [ ] **Step 1: Write the failing test**

Add `INVESTIGATION_WORKFLOW` to the imports at the top of `test/delivery.test.ts`, and add `COMPACT_INSTRUCTIONS` to the existing `callCompact` import. Then append:

```ts
test('agent instructions name delivery, focus, next, and commandless use', () => {
  for (const text of [COMPACT_INSTRUCTIONS, INVESTIGATION_WORKFLOW]) {
    assert.match(text, /delivery complete/);
    assert.match(text, /focus/);
    assert.match(text, /next\.start/);
    assert.match(text, /match false/);
    assert.match(text, /never ask the user to run Julius commands/);
  }
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --import tsx --test test/delivery.test.ts`

Expected: FAIL because the current strings lack `delivery complete`.

- [ ] **Step 3: Write minimal implementation**

Replace `COMPACT_INSTRUCTIONS` with:

```ts
export const COMPACT_INSTRUCTIONS = 'For code changes or debugging, discover investigation.execute and use its change-impact (paths) or failure-localization (literal query) recipe before repeated file reads. Invoke tools yourself; never ask the user to run Julius commands. Use julius_discover for other graph/context schemas, then julius_call. When the task needs one fact, pass that literal as query, pattern, symbol, path, file, or paths, or pass focus to window a broader result around the fact. When the task needs every item in the result, pass delivery complete and omit budget. If the result has next, continue with context.read at next.start. match false means the literal is absent; search the handle with another literal. Results are bounded (default 1200 cl100k_base text tokens) unless delivery complete omits budget; recover omitted content with context.read and byte ranges/search. Graph calls build a local structural index lazily, without model calls. Context operations need no graph. Budget excludes MCP framing. Payload accounting is not provider billing; full recovery can cost more than raw output.';
```

Replace `INVESTIGATION_WORKFLOW` with:

```ts
export const INVESTIGATION_WORKFLOW = `When Julius MCP is available, use it automatically during normal conversation. Discover investigation.execute with julius_discover, then call its change-impact recipe with exact repository-relative paths, or failure-localization with a literal diagnostic fragment. When the task needs one fact, pass that literal as query, pattern, symbol, path, file, or paths, or pass focus to window a broader result around the fact. When the task needs every item in the result, pass delivery complete and omit budget. If the result has next, continue with context.read at next.start. match false means the literal is absent; search the handle with another literal. Use julius_call for execution and context.read recovery. Graph creation and freshness are automatic; never ask the user to run Julius commands or invoke a slash command. Treat results as structural evidence, inspect unknowns and omitted evidence, and use direct source tools when necessary. These MCP instructions take precedence over CLI examples below; CLI examples are an agent-operated fallback when MCP is unavailable.`;
```

In `README.md`, replace the budget paragraph with:

```md
`budget` is 256–16000 `cl100k_base` tokens for the result text, including the
recovery envelope and excluding MCP framing. The default is 1200 when `budget`
is omitted. `delivery` is `selective` or `complete`. `focus` windows a broader
result around one literal. `delivery: "complete"` with `budget` omitted returns
a one-line JSON header, a newline, and the original body; an explicit `budget`
still caps that body and returns `next`. Other omitted results retain an exact
local handle. Use `context.read` with `handle`, byte `start`/`end`, `search`,
or `next.start`. `match: false` means the literal was absent. Graph errors
remain `isError: true`, including when bounded. Each session receives usable
content; no cross-session suppression is assumed. Stats describe the payload
ledger and do not include discovery/schema or protocol costs. Discovery and
stats are small metadata responses, outside the capture ledger and result budget.
```

In `docs/investigations.md`, replace the "Small reports are returned complete." paragraph with:

```md
Small reports are returned complete. Larger reports select whole evidence
records. A call with a literal, or with `focus`, keeps evidence whose path,
name, id, or excerpt contains that literal. `delivery: "complete"` with no
`budget` returns the stored report in one framed body. A retained full report
can be searched or read in byte ranges through `context.read`, continuing at
`next.start` when a cursor is present. Very small budgets fall back to the
ordinary bounded envelope. Execution-limit omissions cannot be recovered from
that report: the agent must narrow or repeat the investigation with different
inputs. Source excerpts are capped at 12 lines/2,000 characters and carry
their original span and completeness.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --import tsx --test test/delivery.test.ts test/investigation.test.ts`

Expected: PASS, including the existing assertion that `COMPACT_INSTRUCTIONS` contains `never ask the user to run Julius commands`.

- [ ] **Step 5: Commit**

```bash
git add src/mcp/compact.ts src/hosts/investigation-instructions.ts README.md docs/investigations.md test/delivery.test.ts
git commit -m "$(cat <<'EOF'
docs: tell agents when to window a result and when to take it whole

EOF
)"
```

---

### Task 7: Offline delivery gate

**Files:**
- Create: `scripts/experiments/delivery-policy-tasks.json`
- Create: `scripts/experiments/delivery-policy.ts`
- Create: `test/delivery-policy.test.ts`

**Interfaces:**
- Consumes: `callCompact`, `Economy.present`, `economyTokens`, `deliverInvestigation`, `runInvestigation`
- Produces:
  - `export function decideDelivery(input: { quality: boolean; policy: { oneFact: number | null; complete: number | null; mixed: number | null }; fixed: { oneFact: number | null; complete: number | null; mixed: number | null } }): 'reject-quality' | 'inconclusive' | 'reject-no-saving' | 'advance-offline-only'`
  - `export async function runDeliveryPolicy(): Promise<{ providerUsage: null; codingTaskAccuracy: null; decision: string; savings: { oneFact: number; complete: number; mixed: number; withoutFlagVersusRaw: number } }>`

- [ ] **Step 1: Write the failing test**

Create `scripts/experiments/delivery-policy-tasks.json`:

```json
{
  "version": 1,
  "purpose": "Frozen selective-delivery falsification set. Not a coding benchmark.",
  "language": "typescript",
  "functions": 180,
  "target": 78,
  "marker": "BENCH_MARKER_078: retry_limit=7",
  "absent": "BENCH_MARKER_MISSING",
  "ambiguous": "Retry",
  "requiredSecond": "AMBIGUOUS_RETRY beta",
  "nonSource": "vendor/readme.txt"
}
```

Create `test/delivery-policy.test.ts`:

```ts
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { decideDelivery, runDeliveryPolicy } from '../scripts/experiments/delivery-policy.js';

test('delivery gate rejects quality loss, unknown tokens, and equal or higher cost', () => {
  const fixed = { oneFact: 100, complete: 100, mixed: 100 };
  assert.equal(decideDelivery({ quality: false, policy: fixed, fixed }), 'reject-quality');
  assert.equal(decideDelivery({ quality: true, policy: { oneFact: null, complete: 1, mixed: 1 }, fixed }), 'inconclusive');
  assert.equal(decideDelivery({ quality: true, policy: fixed, fixed }), 'reject-no-saving');
  assert.equal(decideDelivery({ quality: true, policy: { oneFact: 99, complete: 99, mixed: 99 }, fixed }), 'advance-offline-only');
});

test('offline probe preserves the adverse full-content case and beats fixed preview', async () => {
  const report = await runDeliveryPolicy();
  assert.equal(report.providerUsage, null);
  assert.equal(report.codingTaskAccuracy, null);
  assert.equal(report.decision, 'advance-offline-only');
  assert.ok(report.savings.withoutFlagVersusRaw < 0);
  assert.ok(report.savings.oneFact > 0);
  assert.ok(report.savings.complete > 0);
  assert.ok(report.savings.mixed > 0);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --import tsx --test test/delivery-policy.test.ts`

Expected: FAIL because `../scripts/experiments/delivery-policy.js` does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `scripts/experiments/delivery-policy.ts`:

```ts
import { createHash } from 'node:crypto';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Economy, economyTokens } from '../../src/economy/index.js';
import { deliverInvestigation, runInvestigation } from '../../src/investigation/index.js';
import { callCompact } from '../../src/mcp/compact.js';
import manifest from './delivery-policy-tasks.json' with { type: 'json' };

const wire = (value: unknown) => economyTokens(JSON.stringify(value) + '\n');
function exchange(operation: string, args: object, text: string, extra: { budget?: number; delivery?: string; focus?: string } = {}) {
  return wire({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'julius_call', arguments: { operation, args, ...extra } } })
    + wire({ jsonrpc: '2.0', id: 1, result: { content: [{ type: 'text', text }], isError: false } });
}

export function decideDelivery(input: { quality: boolean; policy: { oneFact: number | null; complete: number | null; mixed: number | null }; fixed: { oneFact: number | null; complete: number | null; mixed: number | null } }) {
  if (!input.quality) return 'reject-quality' as const;
  const cells = ['oneFact', 'complete', 'mixed'] as const;
  if (cells.some(cell => input.policy[cell] === null || input.fixed[cell] === null)) return 'inconclusive' as const;
  if (cells.some(cell => (input.policy[cell] as number) >= (input.fixed[cell] as number))) return 'reject-no-saving' as const;
  return 'advance-offline-only' as const;
}

export function benchListing(): string {
  const lines: string[] = [];
  for (let i = 0; i < manifest.functions; i++) {
    const n = String(i).padStart(3, '0');
    const retry = i === manifest.target ? 7 : 3;
    lines.push(`export function fn${n}() {\n  const pad = '${'x'.repeat(160)}';\n  return ${retry};\n}\n// BENCH_MARKER_${n}: retry_limit=${retry}`);
  }
  lines.push('export function alphaRetry() { return 1; }\n// AMBIGUOUS_RETRY alpha');
  lines.push(`${'gap line\n'.repeat(3000)}export function betaRetry() { return 2; }\n// AMBIGUOUS_RETRY beta`);
  return lines.join('\n');
}

async function reassemble(root: string, handle: string, budget: number, startAt = 0) {
  const economy = new Economy(root);
  let start = startAt;
  const parts: Buffer[] = [];
  let tokens = 0;
  let guard = 0;
  const total = (await economy.read(handle, { budget: 16000, raw: true })).bytes.length;
  while (start < total) {
    const read = await economy.read(handle, { start, budget, transport: 'mcp' });
    parts.push(read.bytes);
    tokens += exchange('context.read', { handle, start }, read.text, { budget });
    const parsed = JSON.parse(read.text);
    const next = parsed.next ? parsed.next.start : parsed.end;
    if (next <= start) throw new Error('fixed recovery did not advance');
    start = next;
    if (++guard > 200) throw new Error('fixed recovery did not finish');
  }
  return { text: Buffer.concat(parts).toString('utf8'), tokens };
}

export async function runDeliveryPolicy() {
  const listing = benchListing();
  if (economyTokens(listing) <= 1200) throw new Error('fixture body fits in the default budget');
  const root = mkdtempSync(join(tmpdir(), 'delivery-policy-'));
  try {
    const fixedPreview = await new Economy(root).present(listing, { algorithm: 'fixed', label: 'fixed', budget: 1200, literals: [] }, 'mcp');
    if (fixedPreview.text.includes(manifest.marker)) throw new Error('head preview already contains the target marker');
    const fixedParsed = JSON.parse(fixedPreview.text);
    const fixedHandle = fixedParsed.handle as string;
    const fixedRead = await new Economy(root).read(fixedHandle, { search: manifest.marker, budget: 1200, transport: 'mcp' });
    const fixedOne = exchange('context.capture', { content: listing }, fixedPreview.text, { budget: 1200 })
      + exchange('context.read', { handle: fixedHandle, search: manifest.marker }, fixedRead.text, { budget: 1200 });
    const fixedTail = await reassemble(root, fixedHandle, 1200, fixedParsed.next.start as number);
    const fixedWhole = `${fixedParsed.content}${fixedTail.text}`;
    if (fixedWhole !== listing) throw new Error('fixed reassembly lost bytes');
    const fixedComplete = exchange('context.capture', { content: listing }, fixedPreview.text, { budget: 1200 }) + fixedTail.tokens;

    const policyOneText = (await callCompact(root, 'julius_call', { operation: 'context.capture', args: { content: listing }, focus: manifest.marker })).text;
    if (!policyOneText.includes(manifest.marker)) throw new Error('policy window missed the marker');
    const policyOne = exchange('context.capture', { content: listing }, policyOneText, { focus: manifest.marker });
    const policyAllText = (await callCompact(root, 'julius_call', { operation: 'context.capture', args: { content: listing }, delivery: 'complete' })).text;
    const split = policyAllText.indexOf('\n');
    const header = JSON.parse(policyAllText.slice(0, split));
    const body = policyAllText.slice(split + 1);
    if (body !== listing) throw new Error('complete body is not verbatim');
    if (createHash('sha256').update(body).digest('hex') !== String(header.handle).slice(7)) throw new Error('complete body does not match the stored object');
    for (let i = 0; i < manifest.functions; i++) if (!body.includes(`BENCH_MARKER_${String(i).padStart(3, '0')}`)) throw new Error('complete body omitted a marker');
    const policyComplete = exchange('context.capture', { content: listing }, policyAllText, { delivery: 'complete' });

    const absent = await callCompact(root, 'julius_call', { operation: 'context.capture', args: { content: listing }, focus: manifest.absent });
    const absentBody = JSON.parse(absent.text);
    if (absent.isError || absentBody.match !== false || absent.text.includes(manifest.marker)) throw new Error('absent hint leaked the fact');
    const absentRead = await callCompact(root, 'julius_call', { operation: 'context.read', args: { handle: absentBody.handle, search: manifest.marker }, budget: 1200 });
    if (!absentRead.text.includes(manifest.marker)) throw new Error('absent recovery missed the fact');
    const absentTokens = exchange('context.capture', { content: listing }, absent.text, { focus: manifest.absent })
      + exchange('context.read', { handle: absentBody.handle, search: manifest.marker }, absentRead.text, { budget: 1200 });

    const ambiguous = await callCompact(root, 'julius_call', { operation: 'context.capture', args: { content: listing }, focus: manifest.ambiguous });
    let ambiguousText = ambiguous.text;
    let ambiguousTokens = exchange('context.capture', { content: listing }, ambiguous.text, { focus: manifest.ambiguous });
    if (!ambiguousText.includes(manifest.requiredSecond)) {
      const parsed = JSON.parse(ambiguous.text);
      let found = false;
      for (const start of (parsed.offsets as number[]).slice(0, 8)) {
        const read = await callCompact(root, 'julius_call', { operation: 'context.read', args: { handle: parsed.handle, start }, budget: 1200 });
        ambiguousTokens += exchange('context.read', { handle: parsed.handle, start }, read.text, { budget: 1200 });
        if (read.text.includes(manifest.requiredSecond)) { found = true; break; }
      }
      if (!found) throw new Error('ambiguous recovery exhausted the offsets');
    }

    mkdirSync(join(root, 'vendor'));
    writeFileSync(join(root, 'vendor', 'readme.txt'), 'not source');
    writeFileSync(join(root, 'mod.ts'), listing);
    const investigated = await runInvestigation(root, { recipe: 'failure-localization', query: 'retry_limit=7' });
    const stored = JSON.stringify(investigated);
    const delivered = JSON.parse(await deliverInvestigation(root, investigated, { algorithm: 'targeted', label: 'targeted', budget: 1200, literals: ['retry_limit=7'] }));
    if (JSON.stringify(delivered.coverage) !== JSON.stringify(investigated.coverage)) throw new Error('coverage changed');
    if (JSON.stringify(delivered.unknowns) !== JSON.stringify(investigated.unknowns)) throw new Error('unknowns changed');
    if (JSON.stringify(delivered).includes(manifest.nonSource)) throw new Error('non-source path entered evidence');
    if (!stored.includes(`"unindexedFiles":${investigated.coverage.unindexedFiles}`)) throw new Error('stored report lost coverage');

    const without = await callCompact(root, 'julius_call', { operation: 'context.capture', args: { content: listing } });
    const withoutParsed = JSON.parse(without.text);
    const withoutTail = await reassemble(root, withoutParsed.handle as string, 1200, withoutParsed.next.start as number);
    if (`${withoutParsed.content}${withoutTail.text}` !== listing) throw new Error('unflagged reassembly lost bytes');
    const withoutTokens = exchange('context.capture', { content: listing }, without.text) + withoutTail.tokens;
    const always = exchange('context.capture', { content: listing }, listing);
    const policy = { oneFact: policyOne, complete: policyComplete, mixed: policyOne + policyComplete };
    const fixed = { oneFact: fixedOne, complete: fixedComplete, mixed: fixedOne + fixedComplete };
    const quality = true;
    return {
      providerUsage: null,
      codingTaskAccuracy: null,
      decision: decideDelivery({ quality, policy, fixed }),
      savings: {
        oneFact: fixed.oneFact - policy.oneFact,
        complete: fixed.complete - policy.complete,
        mixed: fixed.mixed - policy.mixed,
        withoutFlagVersusRaw: always - withoutTokens,
      },
      charged: { absentTokens, ambiguousTokens },
    };
  } finally { rmSync(root, { recursive: true, force: true }); }
}
```

`quality` is assigned `true` only after the throws above have passed. `absentTokens` and `ambiguousTokens` are charged and returned so a later reader can see them; they stay outside `decideDelivery`.

- [ ] **Step 4: Run test to verify it passes**

Run: `node --import tsx --test test/delivery-policy.test.ts`

Expected: PASS, decision `advance-offline-only`, and `withoutFlagVersusRaw < 0`.

Then run: `npm test`

Expected: the full suite passes, including this probe.

- [ ] **Step 5: Commit**

```bash
git add scripts/experiments/delivery-policy-tasks.json scripts/experiments/delivery-policy.ts test/delivery-policy.test.ts
git commit -m "$(cat <<'EOF'
test: gate selective delivery against fixed preview and full recovery

EOF
)"
```
