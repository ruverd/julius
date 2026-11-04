import { createRequire } from 'node:module';
import { basename } from 'node:path';
import { fileURLToPath } from 'node:url';

const native = createRequire(import.meta.url)(process.env.JULIUS_RUST_ADDON ?? fileURLToPath(new URL('./extractor.node', import.meta.url)));
export const counters = { files: 0, nativeMs: 0, materializeMs: 0, bytes: 0 };
export function resetCounters() { for (const key of Object.keys(counters)) counters[key] = 0; }

export function extractRust(rel, source, language, helpers) {
  const started = performance.now();
  const packed = native.extract(source, language);
  const returned = performance.now();
  const [endRow, definitions, edges] = JSON.parse(packed);
  const { contentHash, fileResidual, searchBody, clean } = helpers;
  const bytes = Buffer.from(source, 'utf8');
  const slice = (start, end) => bytes.subarray(start, end).toString('utf8');
  const nodes = [{ id: rel, name: basename(rel), kind: 'file', path: rel, span: `L1-L${endRow}`,
    signature: null, exported: true, origin: 'ast', body_hash: contentHash(source), chars: source.length,
    summary_state: 'pending', summary: null, crux: null }];
  for (const [suffix, name, kind, start, end, header, firstRow, lastRow, exported, owner] of definitions) {
    const body = slice(start, end);
    nodes.push({ id: `${rel}#${suffix}`, name, kind, path: rel, span: `L${firstRow}-L${lastRow}`,
      signature: clean(slice(start, header)), exported, origin: 'ast', body_hash: contentHash(body),
      body_text: searchBody(body), summary_state: 'pending', summary: null, crux: null,
      ...(owner === null ? {} : { owner }) });
  }
  const rawEdges = edges.map(([sourceIndex, relation, target, viaMember, recvType, specifier]) => {
    const edge = { source: nodes[sourceIndex + 1].id, relation, file: rel };
    if (relation === 'contains') edge.targetId = nodes[target + 1].id;
    else if (relation !== 'imports') edge.name = target;
    if (viaMember !== null) edge.viaMember = viaMember;
    if (recvType !== null) edge.recvType = recvType;
    if (specifier !== null) edge.specifier = specifier;
    return edge;
  });
  nodes[0].body_text = fileResidual(source, nodes.slice(1));
  counters.files++; counters.nativeMs += returned - started;
  counters.materializeMs += performance.now() - returned; counters.bytes += Buffer.byteLength(packed);
  return { nodes, rawEdges };
}
