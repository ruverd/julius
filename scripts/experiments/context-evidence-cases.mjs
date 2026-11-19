const decision = (title, touches, lines, metadata = '') =>
  `---\ntitle: ${title}\nauthor: Fixture\ndate: 2025-02-10\n${metadata}${touches.length ? `touches:\n${touches.map(path => `  - ${path}\n`).join('')}` : ''}---\n\n## Decided\n${lines.map(line => `- ${line}\n`).join('')}`;

const note = name => `.julius/learnings/${name}.md`;
const fact = (path, text) => ({ path, text });
const signature = `Recovery capsule signature = ${'grey birch amber indigo violet cedar mint quartz '.repeat(55).trim()}.`;

export const cases = [
  {
    name: 'parallel-state', budget: 300,
    query: 'What is the parallel test policy and where does the test harness share mutable state?',
    files: {
      'src/harness.ts': `const sharedTestState = new Map<string, number>();\nexport function acquireTestLease(key: string) {\n  const current = sharedTestState.get(key) ?? 0;\n  sharedTestState.set(key, current + 1);\n  return current;\n}\n`,
      [note('parallel')]: decision('Parallel test policy', ['src/harness.ts'], [
        'The harness supports both an interactive mode and a scripted mode for development.',
        'Parallel test jobs must use independent processes because the harness mutates shared state.',
      ]),
    },
    facts: [fact(note('parallel'), '- Parallel test jobs must use independent processes because the harness mutates shared state.'),
      fact('src/harness.ts', 'const sharedTestState = new Map<string, number>();'),
      fact('src/harness.ts', '  sharedTestState.set(key, current + 1);')],
  },
  {
    name: 'two-code-sources', budget: 350,
    query: 'What is the warehouse retry policy and how do retryDelay and retryLimit implement it?',
    files: {
      'src/retry-delay.ts': 'export function retryDelay(attempt: number) {\n  return 250 * 2 ** attempt;\n}\n',
      'src/retry-limit.ts': 'export const retryLimit = 4;\n',
      [note('warehouse')]: decision('Warehouse retry policy', ['src/retry-delay.ts', 'src/retry-limit.ts'], [
        'Retry behavior follows the warehouse service contract for all outgoing requests.',
        'Warehouse retry policy allows at most four attempts with exponential backoff.',
      ]),
    },
    facts: [fact(note('warehouse'), '- Warehouse retry policy allows at most four attempts with exponential backoff.'),
      fact('src/retry-delay.ts', '  return 250 * 2 ** attempt;'), fact('src/retry-limit.ts', 'export const retryLimit = 4;')],
  },
  {
    name: 'revision-and-duplicates', budget: 300,
    query: 'Which audit separator policy is active, and how does auditSeparator encode it?',
    files: {
      'src/audit.ts': 'export const auditSeparator = "\\u001f";\n',
      [note('active')]: decision('Audit separator policy', ['src/audit.ts'], ['Audit separator policy requires the ASCII unit separator between fields.'], 'id: l-c0ffee\nreplaces: l-deadbe\n'),
      [note('duplicate')]: decision('Audit separator policy copy', ['src/audit.ts'], ['Audit separator policy requires the ASCII unit separator between fields.']),
      [note('old')]: decision('Audit separator policy', ['src/audit.ts'], ['REPLACED_OLD: Audit separator policy requires commas.'], 'id: l-deadbe\n').replace('2025-02-10', '2024-11-01'),
      [note('held')]: decision('Audit separator policy', ['src/audit.ts'], ['HELD_DRAFT: Audit separator policy requires spaces.'], 'status: held\n'),
      [note('retired')]: decision('Audit separator policy', ['src/audit.ts'], ['RETIRED_RULE: Audit separator policy requires tabs.'], 'status: retired\n'),
    },
    personal: decision('Audit separator policy', ['src/audit.ts'], ['PERSONAL_ONLY: Audit separator policy requires periods.']),
    forbidden: ['REPLACED_OLD', 'HELD_DRAFT', 'RETIRED_RULE'],
    pilotForbidden: ['PERSONAL_ONLY'],
    facts: [fact(note('active'), '- Audit separator policy requires the ASCII unit separator between fields.'),
      fact('src/audit.ts', 'export const auditSeparator = "\\u001f";')],
    duplicate: '- Audit separator policy requires the ASCII unit separator between fields.',
  },
  {
    name: 'code-only', budget: 300,
    query: 'What is maxBatchSize?',
    files: {
      'src/batch.ts': 'export const maxBatchSize = 128;\n',
      [note('unrelated')]: decision('Invoice tax', ['src/invoice.ts'], ['UNRELATED_NOTE: Invoice tax is rounded to cents.']),
    },
    forbidden: ['UNRELATED_NOTE'],
    facts: [fact('src/batch.ts', 'export const maxBatchSize = 128;')],
  },
  {
    name: 'note-only', budget: 300,
    query: 'What is the procurement approval policy?',
    files: {
      'src/palette.ts': 'export const backgroundColor = "purple";\n',
      [note('procurement')]: decision('Procurement approval policy', [], ['Procurement approval requires the budget owner.']),
    },
    forbidden: ['backgroundColor'],
    facts: [fact(note('procurement'), '- Procurement approval requires the budget owner.')],
  },
  {
    name: 'required-recovery', budget: 256,
    query: 'What is the exact recovery capsule signature and what is capsuleVersion?',
    files: {
      'src/capsule.ts': 'export const capsuleVersion = 17;\n',
      [note('capsule')]: decision('Recovery capsule signature', ['src/capsule.ts'], ['Recovery capsule signature is copied verbatim.', signature]),
    },
    facts: [fact(note('capsule'), `- ${signature}`), fact('src/capsule.ts', 'export const capsuleVersion = 17;')],
    requiresRecovery: true,
  },
];
