// Frozen pre-optimization Julius implementation; exact numerical and entry-order oracle.
export function referencePageRank(topology, seeds, opts = {}) {
    const alpha = opts.alpha ?? 0.25;
    const iters = opts.iters ?? 25;
    const ids = topology.ids;
    const adjacency = topology.adjacency;
    // Restart distribution: seed weights, restricted to real nodes, normalized.
    let seedTotal = 0;
    for (const [id, w] of seeds)
        if (ids.has(id) && w > 0)
            seedTotal += w;
    if (seedTotal <= 0)
        return new Map();
    const restart = new Map();
    for (const [id, w] of seeds)
        if (ids.has(id) && w > 0)
            restart.set(id, w / seedTotal);
    // Power iteration from the restart distribution.
    let rank = new Map(restart);
    for (let i = 0; i < iters; i++) {
        const next = new Map();
        // Teleport: every step, alpha of the mass returns to the seed set.
        for (const [id, r] of restart)
            next.set(id, alpha * r);
        // Dangling mass (nodes with no walk edges) is pooled and returned to the
        // seed set ONCE per iteration — same math as redistributing per node, but
        // O(nodes + seeds) instead of O(dangling × seeds).
        let dangling = 0;
        for (const [id, mass] of rank) {
            const nbrs = adjacency.get(id);
            if (!nbrs || nbrs.length === 0) {
                dangling += mass;
                continue;
            }
            const share = ((1 - alpha) * mass) / nbrs.length;
            for (const nb of nbrs)
                next.set(nb, (next.get(nb) ?? 0) + share);
        }
        if (dangling > 0) {
            const dm = (1 - alpha) * dangling;
            for (const [sid, r] of restart)
                next.set(sid, (next.get(sid) ?? 0) + dm * r);
        }
        rank = next;
    }
    let max = 0;
    for (const v of rank.values())
        if (v > max)
            max = v;
    if (max <= 0)
        return new Map();
    const out = new Map();
    for (const [id, v] of rank)
        out.set(id, v / max);
    return out;
}
