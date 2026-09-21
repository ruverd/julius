# Historical local price store

`PriceStore` stores append-only dated price snapshots in a private SQLite WAL database. A snapshot states its endpoint, provider, model, currency, tier, cache regime, source, source date, effective time, optional expiry, four per-million rate categories, and optional contracted rate. Rate values are nonnegative finite decimals; `null` means unavailable. Julius ships no default prices and never fills a missing category with zero.

`record(snapshot)` appends a validated observation. `history(endpoint=..., provider=..., model=...)` returns all observations in insertion order. `lookup(endpoint=..., provider=..., model=..., currency=..., tier=..., cache_regime=..., at=...)` returns `known` with one snapshot, `unknown` with none, or `ambiguous` with candidate IDs when overlapping observations match. Expiry is exclusive. Lookup never silently picks the newest or cheapest price.

The store preserves the source date separately from the local recorded time. A known snapshot is price evidence, not a provider bill or measured savings. Callers must explicitly select a matching snapshot and account for every applicable usage category before modeling cost. An existing database with unsafe permissions or a direct symlink is rejected without modifying it.
