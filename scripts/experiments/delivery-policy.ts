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
  const checks: boolean[] = [];
  try {
    const fixedPreview = await new Economy(root).present(listing, { algorithm: 'fixed', label: 'fixed', budget: 1200, literals: [] }, 'mcp');
    checks.push(!fixedPreview.text.includes(manifest.marker));
    const fixedParsed = JSON.parse(fixedPreview.text);
    const fixedHandle = fixedParsed.handle as string;
    const fixedRead = await new Economy(root).read(fixedHandle, { search: manifest.marker, budget: 1200, transport: 'mcp' });
    const fixedOne = exchange('context.capture', { content: listing }, fixedPreview.text, { budget: 1200 })
      + exchange('context.read', { handle: fixedHandle, search: manifest.marker }, fixedRead.text, { budget: 1200 });
    const fixedTail = await reassemble(root, fixedHandle, 1200, fixedParsed.next.start as number);
    const fixedWhole = `${fixedParsed.content}${fixedTail.text}`;
    checks.push(fixedWhole === listing);
    const fixedComplete = exchange('context.capture', { content: listing }, fixedPreview.text, { budget: 1200 }) + fixedTail.tokens;

    const policyOneText = (await callCompact(root, 'julius_call', { operation: 'context.capture', args: { content: listing }, focus: manifest.marker })).text;
    checks.push(policyOneText.includes(manifest.marker));
    const policyOne = exchange('context.capture', { content: listing }, policyOneText, { focus: manifest.marker });
    const policyAllText = (await callCompact(root, 'julius_call', { operation: 'context.capture', args: { content: listing }, delivery: 'complete' })).text;
    const split = policyAllText.indexOf('\n');
    const header = JSON.parse(policyAllText.slice(0, split));
    const body = policyAllText.slice(split + 1);
    checks.push(body === listing);
    checks.push(createHash('sha256').update(body).digest('hex') === String(header.handle).slice(7));
    for (let i = 0; i < manifest.functions; i++) checks.push(body.includes(`BENCH_MARKER_${String(i).padStart(3, '0')}`));
    const policyComplete = exchange('context.capture', { content: listing }, policyAllText, { delivery: 'complete' });

    const absent = await callCompact(root, 'julius_call', { operation: 'context.capture', args: { content: listing }, focus: manifest.absent });
    const absentBody = JSON.parse(absent.text);
    checks.push(!absent.isError && absentBody.match === false && !absent.text.includes(manifest.marker));
    const absentRead = await callCompact(root, 'julius_call', { operation: 'context.read', args: { handle: absentBody.handle, search: manifest.marker }, budget: 1200 });
    checks.push(absentRead.text.includes(manifest.marker));
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
      checks.push(found);
    }

    mkdirSync(join(root, 'vendor'));
    writeFileSync(join(root, 'vendor', 'readme.txt'), 'not source');
    writeFileSync(join(root, 'mod.ts'), listing);
    const investigated = await runInvestigation(root, { recipe: 'failure-localization', query: 'retry_limit=7' });
    const delivered = JSON.parse(await deliverInvestigation(root, investigated, { algorithm: 'targeted', label: 'targeted', budget: 1200, literals: ['retry_limit=7'] }));
    checks.push(JSON.stringify(delivered.coverage) === JSON.stringify(investigated.coverage));
    checks.push(JSON.stringify(delivered.unknowns) === JSON.stringify(investigated.unknowns));
    checks.push(!JSON.stringify(delivered).includes(manifest.nonSource));

    const without = await callCompact(root, 'julius_call', { operation: 'context.capture', args: { content: listing } });
    const withoutParsed = JSON.parse(without.text);
    const withoutTail = await reassemble(root, withoutParsed.handle as string, 1200, withoutParsed.next.start as number);
    checks.push(`${withoutParsed.content}${withoutTail.text}` === listing);
    const withoutTokens = exchange('context.capture', { content: listing }, without.text) + withoutTail.tokens;
    const always = exchange('context.capture', { content: listing }, listing);
    const policy = { oneFact: policyOne, complete: policyComplete, mixed: policyOne + policyComplete };
    const fixed = { oneFact: fixedOne, complete: fixedComplete, mixed: fixedOne + fixedComplete };
    const quality = checks.every(Boolean);
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
      alwaysComplete: always,
      charged: { absentTokens, ambiguousTokens },
    };
  } finally { rmSync(root, { recursive: true, force: true }); }
}
