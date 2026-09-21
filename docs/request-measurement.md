# Whole-request candidate measurement

`measure_request_pair(original, candidate)` serializes each complete xAI Responses request using the same `XAIAdapter.prepare` path used for sending. The byte counts therefore include instructions, tools, protocol fields, and all input items. `deltaBytes` is before minus after and may be negative. This offline comparison does not send either request.

Token counts stay `null` unless the caller injects a deterministic `token_counter(serialized_request_text)` with explicit `model_id` and `tokenizer_id`. The model ID must match the request's model field. Invalid counts fail closed. These are caller tokenizer counts over serialized JSON, not xAI provider usage or a billing measurement. They may differ from provider tokenization because request framing and server handling are not known here. `deltaTokens` also stays signed.

`prepare_optimized_request` attaches this receipt as `PreparedXAIRequest.measurement`. Preparation still produces only a candidate with `sent: false`; the dispatch path decides whether it was accepted. No direct request savings or financial savings are claimed from this measurement alone.
