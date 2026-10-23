import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Julius } from '../src/engine.js';
import { readGraph, wiringPath } from '../src/graph/write.js';
import { contextDirFor } from '../src/context/node-file.js';

test('deferred model loading preserves real SDK transports for configured providers', async t => {
  for (const provider of ['openai', 'anthropic', 'litellm', 'orcarouter'] as const) {
    await t.test(provider, async () => {
      const root = mkdtempSync(join(tmpdir(), 'julius-lazy-provider-'));
      const requests: string[] = [];
      const symbols = [
        { id: 'core.ts', summary: 'Contains the fixture API.', crux_start: 0, crux_end: 0 },
        { id: 'core.ts#hello', summary: 'Returns the fixture value.', crux_start: 0, crux_end: 0 },
      ];
      const server = createServer((request, response) => {
        const chunks: Buffer[] = [];
        request.on('data', chunk => chunks.push(chunk));
        request.on('end', () => {
          requests.push(Buffer.concat(chunks).toString());
          response.setHeader('content-type', 'application/json');
          response.end(JSON.stringify(provider === 'anthropic'
            ? { id: 'msg_fixture', type: 'message', role: 'assistant', model: 'test-model', stop_reason: 'tool_use', stop_sequence: null,
              content: [{ type: 'tool_use', id: 'tool_fixture', name: 'record_symbols', input: { symbols } }], usage: { input_tokens: 50, output_tokens: 10 } }
            : { id: 'chat_fixture', object: 'chat.completion', created: 0, model: 'test-model',
              choices: [{ index: 0, finish_reason: 'tool_calls', message: { role: 'assistant', content: null,
                tool_calls: [{ id: 'tool_fixture', type: 'function', function: { name: 'record_symbols', arguments: JSON.stringify({ symbols }) } }] } }],
              usage: { prompt_tokens: 50, completion_tokens: 10, total_tokens: 60 } }));
        });
      });
      await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
      try {
        const address = server.address();
        assert.ok(address && typeof address === 'object');
        writeFileSync(join(root, 'core.ts'), 'export function hello() { return 1; }\n');
        const engine = new Julius({ provider, apiKey: 'fixture-key', model: 'test-model', baseUrl: `http://127.0.0.1:${address.port}/v1` });
        await engine.graph(root);
        assert.equal(requests.length, 0);
        const result = await engine.graph(root, { llm: true });
        assert.deepEqual(result.meaning.errors, []);
        assert.equal(requests.length, 1);
        assert.match(requests[0], /test-model/);
        const graph = readGraph(wiringPath(contextDirFor(root)));
        assert.equal(graph?.nodes.find(node => node.id === 'core.ts#hello')?.summary, 'Returns the fixture value.');
      } finally {
        await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
        rmSync(root, { recursive: true, force: true });
      }
    });
  }
});
