import { expect, test, mock } from "bun:test";
import { normalizeAnthropicUsage, normalizeOpenAIUsage } from "../src/adapters";
import { discoverOllama, doctor } from "../src/models";

test("OpenAI preserves nested cache and reasoning counters without adding them to totals", () => {
  const usage = normalizeOpenAIUsage({ usage: { input_tokens: 100, output_tokens: 20, total_tokens: 120,
    input_tokens_details: { cached_tokens: 40 }, output_tokens_details: { reasoning_tokens: 7 } } });
  expect(usage).toMatchObject({ normalizationVersion: 1, inputTokens: 100, uncachedInputTokens: 60, outputTokens: 20, totalTokens: 120,
    cacheReadTokens: 40, cacheWriteTokens: null, reasoningTokens: 7, costUsd: null });
});

test("OpenAI chat shape and missing fields remain distinct from zero", () => {
  const usage = normalizeOpenAIUsage({ prompt_tokens: 10, completion_tokens: 4,
    prompt_tokens_details: { cached_tokens: 0 }, completion_tokens_details: { reasoning_tokens: 0 } });
  expect(usage).toMatchObject({ inputTokens: 10, outputTokens: 4, totalTokens: null,
    cacheReadTokens: 0, reasoningTokens: 0 });
  expect(normalizeOpenAIUsage({}).inputTokens).toBeNull();
});

test("Anthropic keeps separate cache input categories and requires complete data for a total", () => {
  expect(normalizeAnthropicUsage({ usage: { input_tokens: 10, cache_creation_input_tokens: 3,
    cache_read_input_tokens: 5, output_tokens: 2 } })).toMatchObject({ normalizationVersion: 1, inputTokens: 18, uncachedInputTokens: 10,
    cacheWriteTokens: 3, cacheReadTokens: 5, outputTokens: 2, totalTokens: 20 });
  expect(normalizeAnthropicUsage({ input_tokens: 10, output_tokens: 2 })).toMatchObject({ inputTokens: null, uncachedInputTokens: 10, totalTokens: null });
});

test("Ollama joins installed and loaded models using endpoint, digest, and quantization", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = mock(async (url: URL | RequestInfo) => new Response(JSON.stringify({ models: [
    { model: "a:latest", digest: "sha", details: { quantization_level: "Q4" } },
    ...(String(url).endsWith("/api/tags") ? [{ model: "b:latest", digest: "other", details: { quantization_level: "Q8" } }] : []),
  ] }), { status: 200 })) as unknown as typeof fetch;
  try {
    const result = await discoverOllama();
    expect(result.error).toBeNull();
    expect(result.models.map(({ name, installed, loaded }) => ({ name, installed, loaded }))).toEqual([
      { name: "a:latest", installed: true, loaded: true }, { name: "b:latest", installed: true, loaded: false },
    ]);
  } finally { globalThis.fetch = original; }
});

test("Ollama rejects remote endpoints before fetching", async () => {
  const result = await discoverOllama("https://example.com");
  expect(result.models).toEqual([]);
  expect(result.error).toContain("loopback");
});

test("Ollama blocks redirects and retains installed models when loaded state is unavailable", async () => {
  const original = globalThis.fetch;
  const options: RequestInit[] = [];
  globalThis.fetch = mock(async (url: URL | RequestInfo, init?: RequestInit) => {
    options.push(init ?? {});
    if (String(url).endsWith("/api/ps")) throw new Error("Redirect blocked");
    return new Response(JSON.stringify({ models: [{ model: "a:latest", digest: "sha",
      details: { quantization_level: "Q4" } }] }), { status: 200 });
  }) as unknown as typeof fetch;
  try {
    const result = await discoverOllama();
    expect(result.models).toHaveLength(1);
    expect(result.models[0]?.installed).toBe(true);
    expect(result.models[0]?.loaded).toBeNull();
    expect(result.error).toContain("Redirect blocked");
    expect(options.every((option) => option.redirect === "error")).toBe(true);
  } finally { globalThis.fetch = original; }
});

test("doctor claims no usage observation from executable detection alone", async () => {
  const result = await doctor();
  expect(result.clients.map((client) => client.name)).toEqual(["claude", "codex"]);
  for (const client of result.clients) {
    expect(client.capability).toBe("unsupported");
    expect(client.capabilities).toEqual({ canObserveUsage: false, canOptimizeInput: false,
      canImportUsage: false, liveCompatibilityTested: false });
  }
});
