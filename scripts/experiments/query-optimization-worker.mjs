import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const [product, corpus, mode, input] = process.argv.slice(2);
const cases = JSON.parse(readFileSync(input));
const start = performance.now();
const { ask, formatAsk } = await import(pathToFileURL(join(product, 'dist/ask/ask.js')));
const importMs = performance.now() - start;
const iterations = mode === 'warm' ? 5 : 1;
if (mode === 'warm') for (const c of cases) ask(corpus, c.query, c.options);
global.gc?.();
const rows = []; const bodies = [];
for (let repetition = 0; repetition < iterations; repetition++) for (const c of cases) {
  const started = performance.now(); const result = ask(corpus, c.query, c.options);
  const elapsedMs = performance.now() - started;
  const hash = createHash('sha256').update(JSON.stringify(result)).digest('hex');
  rows.push({ id: c.id, repetition, elapsedMs, hash });
  if (mode === 'parity') {
    const text = formatAsk(result);
    for (const hit of result.hits) {
      assert.ok(text.includes(hit.pointer));
      if (hit.snippet) assert.ok(text.includes(hit.snippet), 'Descriptions must survive deduplication');
      if (hit.code) assert.ok(text.includes(hit.code), 'Code evidence must be byte-identical');
    }
    bodies.push({ id: c.id, text });
  }
}
global.gc?.();
const memory = process.memoryUsage();
const { economyTokens } = await import(pathToFileURL(join(product, 'dist/economy/index.js')));
const formatted = bodies.map(({ id, text }) => ({ id, bytes: Buffer.byteLength(text), tokens: economyTokens(text) }));
console.log(JSON.stringify({ importMs, maxRSSKiB: process.resourceUsage().maxRSS, memory, rows, formatted }));
