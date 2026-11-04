export const extractionCases = [
  ['empty.ts', ''],
  ['unicode.ts', '// 🦀 café\r\nexport function ação(á: string) { return "𐐀\u2028β" + á; }\r\n'],
  ['import-shadow.ts', `import { Thing as T, helper } from './core';
export function f(x: T) { x.run(); helper(); return helper; }
export function g(helper: unknown) { return helper; }
function h() { const helper = 1; return helper; }
function outer() { function helper() {} return helper; }
const arrow = (helper: T) => helper.run();`],
  ['bindings.ts', `import { Queue as Q } from './core';
class C extends Base implements Contract {
  q: Q = new Q();
  constructor(private readonly svc: Service, bare: Q) { bare.run(); }
  run() { this.q.put(); this.svc.call(); this.helper(); }
  helper() {}
}
const c = new C(); c.run(); factory().run(); ns.member();`],
  ['duplicates.ts', 'class C { m() {} } class C { m() {} } if (true) { function f() {} } else { function f() {} }'],
  ['shapes.ts', `export interface I { m(): void }
export type T = { x: string }; export enum E { A, B }
export abstract class A { abstract run(): void; }
const fn = function named(x) { return nested(x); };
const gen = function* () { yield fn(); }; function* free() { yield gen(); }
export default function main() { return fn(); }`],
  ['component.tsx', `import { Button, handler as onClick } from './ui';
export const View = () => <Button onClick={onClick}>Olá 🦀</Button>;`],
  ['decorators.ts', '@service() export class C { @log() m() { return this.other?.(); } }'],
  ['malformed.ts', 'export class Broken { m( { return imported; }\nconst x = () => {'],
  ['huge.ts', '// large source\n' + Array.from({ length: 900 }, (_, i) => `export function fn${i}(x: string) { return "item${i} 🦀" + x; }`).join('\n')],
  ['long-body.ts', `export function large() { ${'const repeated = "context";'.repeat(1000)} }`],
  ['module-residual.ts', `import Default, * as ns from './core';\nconst UNIQUE_MODULE_TOKEN = 'transport';\nexport function f() { return ns.run(Default); }`],
  ['nested.ts', 'export function outer() { class Inner { m() { function nested() { return 1; } return nested(); } } return new Inner(); }'],
  ['unusual.ts', 'class C { "with space"() {} [Symbol.iterator]() { return this; } get value() { return 1; } } const {x} = () => 1;'],
];

export const queries = {
  julius: ['buildGraph', 'cache invalidation fingerprint', 'native parser fallback', 'imported symbol reference', 'PageRank ranking', 'who calls extractFile', 'zzzzunmatchable'],
  commander: ['parse arguments', 'option flags', 'command action handler', 'help output', 'who calls parse', 'zzzzunmatchable'],
  'synthetic-large': ['rareNeedle731', 'shared transport retry', 'Worker run', 'core payload', 'who calls core', 'zzzzunmatchable'],
};
export function queryCases(id) {
  return queries[id].flatMap((query, i) => [
    { id: `${i}/default`, query, options: { limit: 8 } },
    { id: `${i}/lexical`, query, options: { limit: 8, graphRank: false, fileFirst: false } },
    { id: `${i}/scoped`, query, options: { limit: 8, in: id === 'julius' ? 'src/graph/' : id === 'commander' ? 'lib/' : 'packages/a/src/' } },
    { id: `${i}/source`, query, options: { limit: 8, source: true, full: true, includeRankingMetadata: true } },
  ]);
}
