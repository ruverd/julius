# Julius stdio contract for Bulma

The local Python process can call `julius.stdio_api.serve_stdio(directory, input_stream, output_stream)` or run `julius serve --data-dir <path>`. It reads newline-delimited JSON requests and writes exactly one JSON response per input line. The caller owns process launch and the local data directory. No model execution is available through this transport.

Each request has exactly four fields: `protocolVersion` (integer `1`), `id` (nonempty string, at most 128 UTF-8 bytes), `operation`, and `params`. IDs are echoed in responses; callers should use unique IDs to match asynchronous work. The supported operations are `optimize` with `{"context": {...}, "policy": {...}}`, `recordUsage` and `recordOutcome` with `{"event": {...}}`, and `report` with `{"query": {...}}`. These call the existing Julius SDK methods. Report queries are local and offline. Event validation and deduplication follow the SDK.

A successful response is `{"protocolVersion":1,"id":"example","ok":true,"result":{...}}`. A failed response is `{"protocolVersion":1,"id":"example","ok":false,"error":"invalid_params"}`. Framing or JSON errors use a null ID when it cannot be recovered. Errors are data; the process continues to the next line. Consumers must check `ok` before reading `result`.

Requests are capped at 1 MiB per line, including the newline; responses are capped at 2 MiB of JSON, excluding the newline. Oversize requests are consumed through their newline and return `request_too_large`. Oversize results return `response_too_large`. Keep each request on one line, encoded as UTF-8, and read one response line before assuming completion. Do not send secrets in requests; the transport intentionally does not provide remote calls or authentication.
