import type { RetainedRange } from './index.js';

export type EvidenceHit = RetainedRange & { content: string; format: string };

/** Render the same selected ranges with shared source declarations and literal quote rows. */
export function evidenceLines(handle: string, hits: EvidenceHit[], more: RetainedRange[]): string | null {
  const sources: string[] = [];
  const ids = new Map<string, number>();
  const location = ({ start, evidence }: RetainedRange) => {
    const { kind, path, heading, from, to } = evidence;
    const source = `${kind} ${JSON.stringify(path)}${heading === undefined ? '' : ` ${JSON.stringify(heading)}`}`;
    let id = ids.get(source);
    if (id === undefined) {
      id = sources.length;
      ids.set(source, id);
      sources.push(`source ${id} ${source}`);
    }
    return `${id} L${from}${to === from ? '' : `-L${to}`} ${start}`;
  };
  const rows: string[] = [];
  for (const hit of hits) {
    // Snapshot quote rows have a reserved prefix. Other retained bytes use the
    // existing JSON envelope instead of introducing a second escaping rule.
    if (hit.format !== 'utf8' || !hit.content.split('\n').every(line => line.startsWith('| '))) return null;
    rows.push(`hit ${location(hit)}`, hit.content);
  }
  for (const range of more) rows.push(`more ${location(range)}:${range.end}`);
  return [`evidence ${handle}`, ...sources, ...rows].join('\n');
}
