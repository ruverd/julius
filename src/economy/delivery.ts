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
