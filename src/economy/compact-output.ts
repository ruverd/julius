export type CompactionFormat = 'tap' | 'log' | 'build';

export function parseCompactionFormat(value: unknown): CompactionFormat {
  if (value === 'tap' || value === 'log' || value === 'build') return value;
  throw new Error('compact must be tap, log or build');
}

export function compactOutput(text: string, kind: CompactionFormat): { text: string; changed: boolean } {
  const lines = text.match(/[^\n]*\n|[^\n]+$/g) ?? [];
  const output: string[] = [];
  let passes = 0;
  const flush = () => {
    if (passes) output.push(`[${passes} passing TAP records omitted; names and timings in original]\n`);
    passes = 0;
  };
  for (let i = 0; i < lines.length;) {
    // Extra diagnostics and unfamiliar TAP records stay verbatim.
    if (kind === 'tap' && /^# Subtest: [^\r\n]+\r?\n$/.test(lines[i]!)
      && /^ok \d+ - [^\r\n]+\r?\n$/.test(lines[i + 1] ?? '')
      && !/ # (?:SKIP|TODO)\b/i.test(lines[i + 1]!)
      && /^  ---\r?\n$/.test(lines[i + 2] ?? '')
      && /^  duration_ms: \d+(?:\.\d+)?\r?\n$/.test(lines[i + 3] ?? '')
      && /^  \.\.\.\r?\n$/.test(lines[i + 4] ?? '')) {
      const name = lines[i]!.replace(/^# Subtest: /, '').trimEnd();
      const resultName = lines[i + 1]!.replace(/^ok \d+ - /, '').trimEnd();
      if (name === resultName) { passes++; i += 5; continue; }
    }
    flush();
    let end = i + 1;
    if (kind !== 'tap' && lines[i]!.endsWith('\n')) {
      while (end < lines.length && lines[end] === lines[i]) end++;
    }
    output.push(lines[i]!);
    if (end - i > 1) output.push(`[previous exact line repeated ${end - i - 1} additional times]\n`);
    i = end;
  }
  flush();
  const compact = output.join('');
  return Buffer.byteLength(compact) < Buffer.byteLength(text)
    ? { text: compact, changed: true } : { text, changed: false };
}
