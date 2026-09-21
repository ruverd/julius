# Event and accounting contract

The executable accepts Julius v1 JSONL events. `python/julius/events.py` exports strict Pydantic schemas and `validate_event`; these are the authoritative runtime contracts. Events have a 64 KiB maximum. Imports have a 16 MiB maximum. Timestamps use canonical UTC ISO strings with milliseconds, for example `2026-09-21T12:00:00.000Z`.

## Identity

Every event has source and source-event IDs. Normalized replay is idempotent; changed content at the same source identity is rejected. Cross-source usage duplicates require explicit call identity and matching ownership/attempt identity. The ledger keeps aliases rather than forgetting the second source. New attempts remain distinct. Importing a changed transcript requires explicit reconciliation instead of silently rewriting an earlier measurement.

## Usage

`inputTokens` is normalized full input, including cache reads and writes when the provider separates them. Cache columns are dimensions of input, not additional amounts to add to it. Anthropic input remains unknown if required cache counters are missing. Output includes reasoning when the provider includes it; nested reasoning details are never added twice. Raw usage and normalizer version may accompany imported events.

Each nullable counter distinguishes unavailable from zero. `complete:false` exposes incomplete usage. `observationScope:'session_delta'` identifies cumulative log deltas that cannot prove a count of individual calls. Model identity is null when actual responding model is unknown. A requested model does not prove actual model identity.

Aggregate `observedCalls` counts distinct call IDs within project, session, client, and provider identity. `usageRecords` counts all usage records, including session deltas and records with unknown call ID. Incomplete call count excludes unknown-ID records; `incompleteUsageRecords` includes them. The dashboard shows these denominators separately. This prevents an imported session total from appearing as one known provider call.

Known `costUsd` requires a known model and `costProvenance`. Caller-modeled prices carry price source, date, and model identity. An xAI provider-reported charge carries `chargeSource: provider_usage`, `chargeField: usage.cost_in_usd_ticks`, `chargeUnit: usd_ticks_1e10`, and actual model identity. Reports separate provider charges from modeled prices. Raw ticks remain in `rawUsage`; the USD float is a display conversion, not billing-grade decimal arithmetic. Financial savings still need a comparable baseline. Auxiliary and restoration categories are part of the same usage sum; their subtotals are never added again.

## Transformations

Only `sent:true` transformations contribute direct input reduction. Scope, model, tokenizer, and evidence remain separate grouping dimensions. Before minus after is a signed marginal reduction. A parent must exist and its output count must match its child's input count. Conflicting sent branches are rejected.

The pure optimizer and CLI preview are not evidence that a request was sent. Harnesses record sending separately. Provider usage cannot establish what an alternative trajectory would have cost. Reported coverage applies only to observed request IDs.

## Corrections and budgets

A reconciliation targets a usage event within matching ownership boundaries. The latest appended correction supplies effective values while history remains available. Query dates select the original usage occurrence; later corrections can update that historical view.

Budget reservations are SQLite transactions shared by processes. IDs are idempotent, releases and expiry leave inactive records, settlement cannot exceed a reservation, and incompatible reuse is rejected. Reservations are admission control, not a provider-side spend cap: callers must reserve conservatively and prevent dispatch after expiry. A crash releases capacity only after reservation expiry.

## Privacy and limits

Aggregate reports omit raw payloads and originals. Source/model/client labels can still identify private work. The SDK accepts trusted local callers, not arbitrary remote clients. Artifact possession alone does not bypass project scope. This release has no network server or sandboxed code execution.

The event store currently retains metadata until the user removes the selected local store. Artifact expiry and deletion are separate. Automatic metadata retention, durable schema migration across released versions, and billing-grade decimal arithmetic remain release work.
