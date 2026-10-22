/** Telemetry needs an explicitly supplied key and host; Julius has no hosted collector. */
export function posthogKey(): string { return process.env.JULIUS_POSTHOG_KEY || ''; }
export function posthogHost(): string { return (process.env.JULIUS_POSTHOG_HOST || '').replace(/\/+$/, ''); }
