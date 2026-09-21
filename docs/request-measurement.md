# Embedded request input measurement

An embedded harness can record direct input reduction after it has sent a request
and received a response. Call `Julius.record_embedded_request` with the complete
model-visible input before and after the transformation, plus the exact input
sent for that attempt. The input strings must include every instruction, tool
definition, and other model-visible segment. Set `complete_model_input=True`
only when this coverage is known. Julius does not infer coverage from a
serialized transport body.

The harness must also supply a pinned tokenizer ID, a counter for that tokenizer,
the corresponding model ID, the actual responding model ID, and the response ID.
The method compares the sent input to the counted after-input and requires the
model IDs to match. The response and completeness claims are caller attestations;
Julius cannot independently verify provider acceptance through this method.

```python
with Julius(".julius") as julius:
    result = julius.record_embedded_request(
        project_id="project", task_id="task", session_id="session",
        request_id="request", attempt_id="attempt", client_id="my-harness",
        model_id="model-version", actual_model_id=response.model,
        response_id=response.id, tokenizer_id="tokenizer-version",
        token_counter=count_model_input_tokens,
        before_input=complete_original_model_input,
        after_input=complete_transformed_model_input,
        sent_input=exact_model_input_sent,
        complete_model_input=True,
    )
```

The resulting request-scope transform uses `tokenizer_counted` evidence and
preserves signed reductions, including negative values. This is a
caller-attested count, not a provider measurement or proof of causal savings.
The ledger stores counts, SHA-256 digests, byte lengths, IDs, and the response
identity. It does not store the input text. Repeating the same attempt returns
an idempotent receipt; changing its attestation raises a conflict.

For a harness that has a usage event, call `record_embedded_attempt` with the
same arguments and `usage_event=<validated usage event>`. It writes the
caller-attested transform and the usage event in one SQLite transaction. The
usage event must have a distinct event ID, a nonempty `callId`, and matching
project, task, session, request, attempt, client, and actual model IDs. Its
observation scope must be `call`. A rejection
leaves neither event from that call behind. Replay with identical inputs is
idempotent; each retry needs its own attempt ID and observed call ID.

Usage remains separate evidence. Supply observed counters and cost only when
the harness actually has them; use `None` for unknown input, output, cache, or
cost values and `complete=False` for incomplete usage. Julius does not infer
provider usage, cost, or a response identity from the token counter. The
existing `record_embedded_request` method still records only the transform;
`record_usage` can be called separately with the same request and attempt IDs.

The separate `send_xai_optimized` path remains fail-closed for caller counters:
it does not promote serialized request counts to verified model-input counts.

## xAI serialized-request comparison

`measure_request_pair(original, candidate)` serializes each complete xAI Responses request using the same `XAIAdapter.prepare` path used for sending. Byte counts therefore include instructions, tools, protocol fields, and input items. `deltaBytes` is before minus after and may be negative. This offline comparison does not send either request.

Token counts stay `null` unless the caller injects a deterministic `token_counter(serialized_request_text)` with explicit `model_id` and `tokenizer_id`. The model ID must match the request's model field. Invalid counts fail closed. Such counts are caller-supplied diagnostics over a serialized JSON body. Even `token_counting_basis="model_input"` cannot prove that a callback covered every model-visible field or provider framing. It does not promote the count to measured direct model-input savings.

`prepare_optimized_request` attaches that receipt to a candidate with `sent: false`. `Julius.send_xai_optimized` records one request-scope transform tied to its first attempt only after response identity and transport-body integrity checks. Without a validated complete input counter for that provider request, event token counts remain unavailable. `tokenComparisonReason` names the missing verification. Julius does not equate a requested alias with a different responding model.

xAI's [billing FAQ](https://docs.x.ai/developers/faq/billing) says inference endpoints add processing tokens, so even its [standalone tokenize-text endpoint](https://docs.x.ai/developers/rest-api-reference/inference/other) can differ from prompt tokens billed on an inference call. Julius has no built-in verified xAI request-level counter. Ordinary CLI safe mode reports serialized-byte change and provider usage separately; direct xAI input-token reduction remains unavailable.

Request-scope changes and tool-output component changes can describe the same reduction. Do not add those scopes. Neither byte change nor a counted input pair proves a cheaper task trajectory or financial savings.
