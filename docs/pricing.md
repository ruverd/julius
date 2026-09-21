# Optional modeled pricing

Pricing is offline and opt in. Julius ships no default price table. A caller supplies an immutable price snapshot dictionary with source, effective time, model, provider, tier, USD currency, and separate rates per million uncached input, cache reads, cache writes, and output tokens. A snapshot is selected explicitly by ID for each usage record; a missing or mismatched snapshot returns `modeledCostUsd: null`.

`price_usage` requires a usage `occurredAt` timestamp before returning a known modeled cost. The snapshot must be effective at that instant. Optional `expiresAt` ends applicability exclusively. Without an expiry, an explicitly selected snapshot remains available for historical modeling. Missing or timezone-naive usage dates return an unknown cost; malformed snapshot dates are rejected.

`price_usage` expects normalized input tokens that already include cache reads and writes. It subtracts both cache categories to find uncached input, then prices each category exactly once. A missing counter or a missing rate for a positive category makes the modeled cost unavailable. Zero counted tokens need no rate. This is a model of cost, never a provider bill.

`compare_modeled_costs` requires a named baseline with either `reconstructed_baseline` or `controlled_experiment` evidence and a stated comparison scope. It sums each supplied primary or auxiliary call once, adds each explicit local or external overhead once, and returns a signed net difference. Negative results remain negative. Unknown baseline, usage, or overhead cost yields a null net result. The comparison does not establish causal savings or subscription impact.

An empty usage list has unknown coverage and produces a null observed cost by default. A caller may explicitly pass `coverage_complete=True` as the fourth argument when it knows the comparison scope contained zero calls; only then is an empty list priced at zero. All four rate keys must be present, with null indicating an unavailable rate.
