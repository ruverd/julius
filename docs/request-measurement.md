# Whole-request candidate measurement

`measure_request_pair(original, candidate)` serializes each complete xAI Responses request using the same `XAIAdapter.prepare` path used for sending. The byte counts therefore include instructions, tools, protocol fields, and all input items. `deltaBytes` is before minus after and may be negative. This offline comparison does not send either request.

Token counts stay `null` unless the caller injects a deterministic `token_counter(serialized_request_text)` with explicit `model_id` and `tokenizer_id`. The model ID must match the request's model field. Invalid counts fail closed. These are caller tokenizer counts over serialized JSON, not xAI provider usage or a billing measurement. They may differ from provider tokenization because request framing and server handling are not known here. `deltaTokens` also stays signed.

`prepare_optimized_request` attaches this receipt as `PreparedXAIRequest.measurement`. Preparation still produces only a candidate with `sent: false`. `Julius.send_xai_optimized` returns a `requestMeasurement` receipt and records one request-scope transform tied to the first provider attempt. It marks the transform sent only after a complete first response confirms the accepted request. If no pinned counter is supplied, or the actual response model differs from the counter's model, the event keeps token counts unavailable. A caller-injected counter gives `tokenizer_counted` evidence, never `provider_reported` evidence.

The request-scope event describes the full serialized request; tool-output candidate events describe individual components. Do not add those two scopes as if they were independent savings. Neither byte change nor tokenizer count proves a cheaper task trajectory or financial savings.
