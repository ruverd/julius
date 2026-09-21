export interface OptimizationPolicy {
  mode: 'observe' | 'safe';
  version: string;
  expiresAt?: string;
  disabled?: boolean;
  approved?: boolean;
  allowRecompression?: boolean;
}

export function policyDecision(policy: OptimizationPolicy): string | null {
  if (policy.disabled) return 'policy_disabled';
  if (!policy.version || !/^\d+\.\d+\.\d+$/.test(policy.version)) return 'invalid_policy_version';
  if (policy.expiresAt && (!Number.isFinite(Date.parse(policy.expiresAt)) || Date.parse(policy.expiresAt) <= Date.now())) return 'policy_expired';
  if (policy.mode !== 'safe' && policy.mode !== 'observe') return 'invalid_policy_mode';
  if (policy.mode === 'safe' && policy.approved !== true) return 'approval_required';
  return null;
}
