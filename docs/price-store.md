# Historical local price store

`PriceStore` stores append-only dated price snapshots in a private SQLite WAL database. A snapshot states its endpoint, provider, model, currency, tier, cache regime, source, source date, effective time, optional expiry, four per-million rate categories, and optional contracted rate. Rate values are nonnegative finite decimals; `null` means unavailable. Julius ships no default prices and never fills a missing category with zero.

The CLI uses `<data-dir>/prices.sqlite3` for the same local store. Record a JSON snapshot, inspect its insertion history, then look up prices at an explicit timestamp:

```sh
julius prices record --state-file price.json --data-dir .julius
julius prices history --endpoint https://api.example.test/v1 --provider example --model model-a --data-dir .julius
julius prices lookup --endpoint https://api.example.test/v1 --provider example --model model-a \
  --currency USD --tier standard --cache-regime default --at 2026-09-15T00:00:00Z --data-dir .julius
```

`price.json` uses these field names and JSON decimal strings:

```json
{
  "endpoint": "https://api.example.test/v1",
  "provider": "example",
  "model": "model-a",
  "currency": "USD",
  "tier": "standard",
  "cache_regime": "default",
  "source": "provider-price-page",
  "source_date": "2026-08-20",
  "effective_at": "2026-09-01T00:00:00Z",
  "expires_at": "2026-10-01T00:00:00Z",
  "rates_per_million": {
    "inputUncached": "1.25",
    "cacheRead": null,
    "cacheWrite": null,
    "output": "4.50"
  }
}
```

The optional `contracted_rate_per_million` field may be a decimal string or `null`. Lookup requires a timezone-aware `--at` value. Its JSON result contains `status`, `snapshot`, and `candidateIds`; an unknown or ambiguous result has a null snapshot.

`record(snapshot)` appends a validated observation. `history(endpoint=..., provider=..., model=...)` returns all observations in insertion order. `lookup(endpoint=..., provider=..., model=..., currency=..., tier=..., cache_regime=..., at=...)` returns `known` with one snapshot, `unknown` with none, or `ambiguous` with candidate IDs when overlapping observations match. Expiry is exclusive. Lookup never silently picks the newest or cheapest price.

The store preserves the source date separately from the local recorded time. A known snapshot is price evidence, not a provider bill or measured savings. Callers must explicitly select a matching snapshot and account for every applicable usage category before modeling cost. An existing database with unsafe permissions or a direct symlink is rejected without modifying it.

For offline task economics, read an exact stored ID with `get_by_id(snapshot_id)`. It returns the recorded JSON object or `None`; it does not choose a current or recent price. To pass that evidence to `price_usage` or `analyze_task`, call `pricing_snapshot(snapshot_id, provider_id=..., model_id=...)`. This returns the pricing-compatible object, keyed by its `id`, only when the selected record uses USD and its provider and model exactly match the supplied usage identity. Missing IDs, other currencies, and identity mismatches return `None`, leaving modeled cost unavailable. The bridge never converts currencies or picks a model, tier, or rate on the caller's behalf.

The converted object retains the source, source date, recorded time, effective time, exclusive expiry, endpoint, tier, cache regime, and all four rate categories. Decimal rates become finite numbers for the existing pricing API; a positive rate that would underflow to zero or a rate that would overflow is unavailable. A `null` cache rate remains `null`, so calls using that category cannot acquire a modeled cost. The optional contracted rate remains provenance and never substitutes for a missing category rate. `price_usage` also checks the usage snapshot ID, provider, model, and occurrence time before pricing.
