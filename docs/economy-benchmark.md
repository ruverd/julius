# Offline context economy benchmark

Reproduce with `npm run build && npm run benchmark:economy`. Regenerate the sample
with `npm run benchmark:economy -- --write`. The checked-in JSON has no local paths,
wall-clock timings, credentials or provider claims.

The harness freezes varied tool-result fixtures at the graph-result boundary:
passing tests, a diagnostic in the middle of a log, a long line, source-like text,
Unicode/CRLF, tiny output, deterministic high-entropy text, every-byte-required
recovery, and a pathological input with unknown token count. No external command
is rerun for a baseline, and no graph engine or model is executed by this harness.

Every fixture declares expected facts independently of its preview. Missing facts
are recovered using separately declared query hints (for example `MAX_RETRIES`,
not the expected value). The harness asserts full expected text appears and
verifies original bytes separately. Every-byte-required recovery follows byte
ranges through the entire object and charges all deliveries. This proves fixture
fact recovery and reversibility, not relevance on a real coding task.

Three categories remain separate:

1. **Raw output:** token count of the original fixture alone.
2. **Inherited-style interface:** the current six inherited Julius graph schemas
   and initialization instructions, an ordinary graph invocation request, and the
   same frozen raw result. This is derived from Trail-Code source SHA
   `b1211efd3eef0efa121b93800e5dd8e547aead77`, not a run of that upstream binary.
3. **Compact Julius:** two tool schemas, compact initialization instructions,
   summary discovery and selected schema requests/responses, invocation, bounded
   result, selected recovery schema, and every follow-up request/response.

Each fixture starts a fresh logical session, so interface overhead is charged
fully rather than amortized across an invented workload. Counts include the exact
JSON-RPC NDJSON envelope, initialization and tool-list requests/responses,
notifications, content escaping and result/error flags. Only `content` is sent;
there is no duplicate `structuredContent`. `textTokens` is descriptive and is not
added again to `responseTokens`. No provider's private message framing is known.

`cl100k_base` is a named offline encoding, not a universal model tokenizer. Runs
over the Economy accounting limit become null and propagate to differences.
Provider usage, provider cost and coding-task accuracy are explicitly null.
Local full-byte integrity checks are not agent-visible deliveries; only the
all-original-needed scenario charges full recovery as conversation traffic.

Small outputs can lose after discovery and wrappers. Full retrieval can erase
all savings and cost more than raw output. The experiment supports local payload
and interface comparisons only. Model/provider/host-specific trials with matched
tasks and outcome checks are needed before claiming actual invoice savings.
