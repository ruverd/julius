/** Provider-reported counters. A null counter was not reported; it is never inferred as zero. */
export interface NormalizedUsage {
  provider: "openai" | "anthropic";
  normalizationVersion: 1;
  inputTokens: number | null;
  uncachedInputTokens: number | null;
  outputTokens: number | null;
  totalTokens: number | null;
  cacheReadTokens: number | null;
  cacheWriteTokens: number | null;
  reasoningTokens: number | null;
  costUsd: null;
  evidence: "provider_reported";
  raw: unknown;
}

type JsonObject = Record<string, unknown>;

function object(value: unknown): JsonObject | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as JsonObject : null;
}

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null;
}

/** Accepts a Responses usage object, a Chat Completions usage object, or their enclosing response. */
export function normalizeOpenAIUsage(raw: unknown): NormalizedUsage {
  const envelope = object(raw);
  const usage = object(envelope?.usage) ?? envelope;
  const input = count(usage?.input_tokens ?? usage?.prompt_tokens);
  const output = count(usage?.output_tokens ?? usage?.completion_tokens);
  const details = object(usage?.input_tokens_details ?? usage?.prompt_tokens_details);
  const outputDetails = object(usage?.output_tokens_details ?? usage?.completion_tokens_details);
  const cacheRead = count(details?.cached_tokens);
  const reasoning = count(outputDetails?.reasoning_tokens);
  return {
    provider: "openai", normalizationVersion: 1, inputTokens: input,
    uncachedInputTokens: input !== null && cacheRead !== null && cacheRead <= input ? input - cacheRead : null,
    outputTokens: output,
    totalTokens: count(usage?.total_tokens), cacheReadTokens: cacheRead,
    cacheWriteTokens: null, reasoningTokens: reasoning, costUsd: null,
    evidence: "provider_reported", raw,
  };
}

/** Anthropic's input_tokens excludes cache reads and writes; all three remain separate. */
export function normalizeAnthropicUsage(raw: unknown): NormalizedUsage {
  const envelope = object(raw);
  const usage = object(envelope?.usage) ?? envelope;
  const uncachedInput = count(usage?.input_tokens);
  const output = count(usage?.output_tokens);
  const cacheRead = count(usage?.cache_read_input_tokens);
  const cacheWrite = count(usage?.cache_creation_input_tokens);
  const input = uncachedInput !== null && cacheRead !== null && cacheWrite !== null &&
    Number.isSafeInteger(uncachedInput + cacheRead + cacheWrite)
    ? uncachedInput + cacheRead + cacheWrite : null;
  const total = input !== null && output !== null && Number.isSafeInteger(input + output)
    ? input + output : null;
  return {
    provider: "anthropic", normalizationVersion: 1, inputTokens: input,
    uncachedInputTokens: uncachedInput, outputTokens: output,
    totalTokens: total, cacheReadTokens: cacheRead, cacheWriteTokens: cacheWrite,
    reasoningTokens: null, costUsd: null, evidence: "provider_reported", raw,
  };
}
