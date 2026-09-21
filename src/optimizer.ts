import { policyDecision, type OptimizationPolicy } from './policy';

export interface OptimizationContext {
  projectId: string;
  content: string;
  category: string;
  protected?: boolean;
  priorTransformId?: string;
  recovery?: { artifactId: string; available: true };
}

export interface OptimizationReceipt {
  scope: 'tool_output';
  applied: boolean;
  reason: string;
  policyVersion: string;
  beforeBytes: number;
  afterBytes: number;
  beforeTokens: number;
  afterTokens: number;
  tokenEstimateMethod: 'heuristic_utf8_bytes_divided_by_4';
  evidence: 'heuristic_estimate';
  tokenizer: null;
  realizedSavings: null;
  lineage: { priorTransformId: string | null; originalArtifactId: string | null };
}

export function optimize(context: OptimizationContext, policy: OptimizationPolicy): { candidate: string; receipt: OptimizationReceipt } {
  if (typeof context.content !== 'string') throw new TypeError('Content must be a string');
  const beforeBytes = Buffer.byteLength(context.content);
  if (beforeBytes > 1024 * 1024) throw new RangeError('Content too large');
  let candidate = context.content;
  const decision = policyDecision(policy);
  let reason = decision ?? 'no_reducible_lines';
  if (!decision) {
    if (context.category !== 'tool_output') reason = 'ineligible_scope';
    else if (context.protected || /\b(error|exception|warning|denied|permission|approval|instruction|system prompt|fail(?:ed|ure)?|assert(?:ion)?|panic|stack trace|traceback)\b/i.test(context.content) || /[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(context.content) || /```|-----BEGIN [A-Z ]+-----/.test(context.content)) reason = 'protected_content';
    else if (context.priorTransformId && !policy.allowRecompression) reason = 'recompression_requires_opt_in';
    else if (policy.mode === 'observe') reason = 'observe_mode';
    else if (!context.recovery || context.recovery.available !== true || !/^[a-f0-9-]{36}$/.test(context.recovery.artifactId)) reason = 'recovery_required';
    else {
      // Only repeated, exact, neutral lines are replaced. A caller must retain the original
      // through its own artifact lifecycle before sending a candidate.
      const lines = context.content.split('\n');
      const counts = new Map<string, number>();
      for (const line of lines) if (/^[\w .,:;/()\-]{16,}$/.test(line)) counts.set(line, (counts.get(line) ?? 0) + 1);
      const seen = new Map<string, number>();
      const reduced = lines.map(line => {
        const count = counts.get(line) ?? 0;
        if (count < 3) return line;
        const ordinal = (seen.get(line) ?? 0) + 1;
        seen.set(line, ordinal);
        return ordinal === 1 ? line : `[repeated exact line ${ordinal}/${count}; restore artifact ${context.recovery?.artifactId}]`;
      }).join('\n');
      if (Buffer.byteLength(reduced) < beforeBytes) { candidate = reduced; reason = 'repeated_exact_lines'; }
    }
  }
  const afterBytes = Buffer.byteLength(candidate);
  return { candidate, receipt: {
    scope: 'tool_output', applied: candidate !== context.content, reason,
    policyVersion: policy.version, beforeBytes, afterBytes,
    beforeTokens: Math.ceil(beforeBytes / 4), afterTokens: Math.ceil(afterBytes / 4),
    tokenEstimateMethod: 'heuristic_utf8_bytes_divided_by_4', evidence: 'heuristic_estimate', tokenizer: null, realizedSavings: null,
    lineage: { priorTransformId: context.priorTransformId ?? null, originalArtifactId: candidate !== context.content ? context.recovery?.artifactId ?? null : null },
  } };
}
