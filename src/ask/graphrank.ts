/**
 * Graph-rank re-ranking for `julius ask` — the fix for lexical keyword-collision.
 *
 * Pure term-overlap ranking treats every node independently, so a node that
 * merely shares a word with the query (a window "overlay" widget) can outrank
 * the node the query is actually about (a scroll-"overlay" config) purely on
 * word count. The graph knows better: the right node is the one wired into the
 * cluster of code the query touches.
 *
 * This module runs personalized PageRank (random-walk-with-restart) over the
 * wiring graph, seeded by the lexical scores. Mass concentrates on nodes that
 * are edge-connected to the matched set; a lexically-matched but structurally
 * isolated node keeps only its own restart mass and sinks. "Lexical proposes,
 * graph disposes." Deterministic, $0, no embeddings — a lexical-seed →
 * graph-rank pipeline, the established alternative to vector search for code.
 */
import type { GraphV1 } from "../graph/types.js";
import { WALK_RELATIONS } from "../graph/relations.js";

export interface PageRankOptions {
  /** Restart probability — the mass that teleports back to the seed set each
   * step. Higher keeps the walk closer to the seeds. 0.25 is the standard value. */
  alpha?: number;
  /** Power-iteration count. 25 is plenty to converge on graphs this size. */
  iters?: number;
  /** Restrict the walk to a subgraph: when present, an edge counts only when
   * BOTH endpoints pass, and only passing ids can hold rank mass or seed
   * weight. Seeds outside the filter are silently ignored (same as a seed
   * naming a non-existent node). Omit for the full-graph walk (unchanged
   * behavior). */
  nodeFilter?: (id: string) => boolean;
}

/** Immutable graph topology consumed by the PageRank iteration. Preparing it
 * separately lets a multi-scope query partition one large graph once, instead
 * of rescanning every node and edge for every scope. */
export interface PageRankTopology {
  ids: ReadonlySet<string>;
  adjacency: ReadonlyMap<string, readonly string[]>;
}

export type PageRankRunOptions = Pick<PageRankOptions, "alpha" | "iters">;

interface MutablePageRankTopology {
  ids: Set<string>;
  adjacency: Map<string, string[]>;
}

const emptyTopology = (): PageRankTopology => ({
  ids: new Set<string>(),
  adjacency: new Map<string, readonly string[]>(),
});

const link = (adjacency: Map<string, string[]>, source: string, target: string): void => {
  const neighbours = adjacency.get(source);
  if (neighbours) neighbours.push(target);
  else adjacency.set(source, [target]);
};

/** Build independent PageRank topologies in one node pass and one edge pass.
 * Edges crossing partitions are excluded, exactly like applying a nodeFilter
 * for each partition independently. Returning `undefined` omits a node. */
export function preparePageRankPartitions(
  graph: GraphV1,
  partitionOfId: (id: string) => string | undefined,
): Map<string, PageRankTopology> {
  const partitionById = new Map<string, string>();
  const mutable = new Map<string, MutablePageRankTopology>();

  for (const node of graph.nodes) {
    const partition = partitionOfId(node.id);
    if (partition === undefined) continue;
    partitionById.set(node.id, partition);
    const topology = mutable.get(partition);
    if (topology) topology.ids.add(node.id);
    else mutable.set(partition, { ids: new Set([node.id]), adjacency: new Map() });
  }

  for (const edge of graph.edges) {
    if (!WALK_RELATIONS.has(edge.relation)) continue;
    const partition = partitionById.get(edge.source);
    if (partition === undefined || partitionById.get(edge.target) !== partition) continue;
    const topology = mutable.get(partition)!;
    link(topology.adjacency, edge.source, edge.target);
    link(topology.adjacency, edge.target, edge.source);
  }

  return new Map(mutable);
}

/** Prepare one optionally filtered topology. Kept public for callers/tests that
 * reuse the same graph across multiple seed sets. */
export function preparePageRankTopology(
  graph: GraphV1,
  nodeFilter?: (id: string) => boolean,
): PageRankTopology {
  const ids = new Set(
    graph.nodes.map((node) => node.id).filter((id) => !nodeFilter || nodeFilter(id)),
  );
  if (ids.size === 0) return emptyTopology();

  const adjacency = new Map<string, string[]>();
  for (const edge of graph.edges) {
    if (!WALK_RELATIONS.has(edge.relation)) continue;
    if (!ids.has(edge.source) || !ids.has(edge.target)) continue;
    link(adjacency, edge.source, edge.target);
    link(adjacency, edge.target, edge.source);
  }
  return { ids, adjacency };
}

/**
 * Personalized PageRank over the wiring graph.
 *
 * `seeds` maps node id → restart weight (a node's lexical score; only positive
 * weights matter). The graph is treated as UNDIRECTED — for "understand this
 * area" a callee is as relevant as a caller. Returns a score per node
 * normalized so the top node is 1; nodes untouched by the walk are absent.
 *
 * Edges whose endpoints aren't both real nodes (e.g. an unresolved import
 * module string) are ignored, so only genuine symbol-to-symbol wiring counts.
 */
export function personalizedPageRank(
  graph: GraphV1,
  seeds: Map<string, number>,
  opts: PageRankOptions = {},
): Map<string, number> {
  return personalizedPageRankPrepared(
    preparePageRankTopology(graph, opts.nodeFilter),
    seeds,
    opts,
  );
}

/** Run PageRank on an already prepared topology. This is numerically identical
 * to {@link personalizedPageRank}; it only removes repeated topology scans. */
export function personalizedPageRankPrepared(
  topology: PageRankTopology,
  seeds: Map<string, number>,
  opts: PageRankRunOptions = {},
): Map<string, number> {
  const alpha = opts.alpha ?? 0.25;
  const iters = opts.iters ?? 25;
  const ids = topology.ids;
  const adjacency = topology.adjacency;

  // Restart distribution: seed weights, restricted to real nodes, normalized.
  let seedTotal = 0;
  for (const [id, w] of seeds) if (ids.has(id) && w > 0) seedTotal += w;
  if (seedTotal <= 0) return new Map();
  if (ids.size < 256) return sparsePageRank(topology, seeds, seedTotal, alpha, iters);
  const names = [...ids];
  const ordinal = new Map(names.map((id, index) => [id, index]));
  for (const [id, neighbours] of adjacency) {
    for (const name of [id, ...neighbours]) {
      if (!ordinal.has(name)) { ordinal.set(name, names.length); names.push(name); }
    }
  }
  const neighbours = names.map(id => (adjacency.get(id) ?? []).map(name => ordinal.get(name)!));
  const restart: Array<[number, number]> = [];
  for (const [id, w] of seeds)
    if (ids.has(id) && w > 0) restart.push([ordinal.get(id)!, w / seedTotal]);

  let rank = new Float64Array(names.length);
  let next = new Float64Array(names.length);
  let active = restart.map(([id]) => id);
  let nextActive: number[] = [];
  const seen = new Uint8Array(names.length);
  for (const [id, r] of restart) rank[id] = r;
  for (let i = 0; i < iters; i++) {
    nextActive.length = 0;
    seen.fill(0);
    for (const [id, r] of restart) {
      next[id] = alpha * r; seen[id] = 1; nextActive.push(id);
    }
    let dangling = 0;
    // Preserve Map insertion order: it determines floating-point addition order.
    for (const id of active) {
      const mass = rank[id]!;
      const nbrs = neighbours[id]!;
      if (nbrs.length === 0) {
        dangling += mass;
        continue;
      }
      const share = ((1 - alpha) * mass) / nbrs.length;
      for (const nb of nbrs) {
        const prior = seen[nb] ? next[nb]! : 0;
        if (!seen[nb]) { seen[nb] = 1; nextActive.push(nb); }
        next[nb] = prior + share;
      }
    }
    if (dangling > 0) {
      const dm = (1 - alpha) * dangling;
      for (const [sid, r] of restart) next[sid] = next[sid]! + dm * r;
    }
    [rank, next] = [next, rank];
    [active, nextActive] = [nextActive, active];
  }

  let max = 0;
  for (const id of active) if (rank[id]! > max) max = rank[id]!;
  if (max <= 0) return new Map();
  const out = new Map<string, number>();
  for (const id of active) out.set(names[id]!, rank[id]! / max);
  return out;
}

function sparsePageRank(
  topology: PageRankTopology,
  seeds: Map<string, number>,
  seedTotal: number,
  alpha: number,
  iters: number,
): Map<string, number> {
  const restart = new Map<string, number>();
  for (const [id, w] of seeds)
    if (topology.ids.has(id) && w > 0) restart.set(id, w / seedTotal);
  let rank = new Map(restart);
  for (let i = 0; i < iters; i++) {
    const next = new Map<string, number>();
    for (const [id, r] of restart) next.set(id, alpha * r);
    let dangling = 0;
    for (const [id, mass] of rank) {
      const neighbours = topology.adjacency.get(id);
      if (!neighbours?.length) { dangling += mass; continue; }
      const share = ((1 - alpha) * mass) / neighbours.length;
      for (const neighbour of neighbours) next.set(neighbour, (next.get(neighbour) ?? 0) + share);
    }
    if (dangling > 0) {
      const dm = (1 - alpha) * dangling;
      for (const [id, r] of restart) next.set(id, (next.get(id) ?? 0) + dm * r);
    }
    rank = next;
  }
  let max = 0;
  for (const value of rank.values()) if (value > max) max = value;
  if (max <= 0) return new Map();
  const out = new Map<string, number>();
  for (const [id, value] of rank) out.set(id, value / max);
  return out;
}
