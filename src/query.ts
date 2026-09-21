export interface QueryWindow { since: string; until: string; timezone: string }

export function queryWindow(options: { since?: string; until?: string }, now = new Date()): QueryWindow {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const end = options.until ? parseDate(options.until) : now;
  const duration = /^(\d+)([dhm])$/.exec(options.since ?? '7d');
  const start = duration
    ? new Date(end.getTime() - Number(duration[1]) * ({ d: 86400000, h: 3600000, m: 60000 }[duration[2]!]!))
    : parseDate(options.since!);
  if (!Number.isFinite(start.getTime()) || start >= end) throw new Error('The start must precede the exclusive end.');
  return { since: start.toISOString(), until: end.toISOString(), timezone };
}

function parseDate(value: string): Date {
  if (!/^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(value)) throw new Error(`Invalid date: ${value}`);
  const day = value.slice(0, 10);
  const check = new Date(`${day}T00:00:00Z`);
  if (!Number.isFinite(check.getTime()) || check.toISOString().slice(0, 10) !== day) throw new Error(`Invalid date: ${value}`);
  const date = new Date(value.length === 10 ? `${value}T00:00:00` : value);
  if (!Number.isFinite(date.getTime())) throw new Error(`Invalid date: ${value}`);
  return date;
}
