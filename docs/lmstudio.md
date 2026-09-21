# Local LM Studio model discovery

`julius.lmstudio.discover_lmstudio(endpoint="http://127.0.0.1:1234", api_token=None)` makes one read-only `GET /api/v1/models` request to a literal loopback IP address. It does not load, download, or run a model. Pass an API token explicitly if the local server requires authentication. Julius does not read LM Studio configuration or credentials. The endpoint identity is included in each model ID so identical keys on separate local servers remain distinct.

The native v1 list includes locally available models. Julius reports each listed model as `installed=True`; `loaded` is true when `loaded_instances` is nonempty, false when it is empty, and null when that field is absent or malformed. Quantization and selected variant are retained when supplied. The documented response does not expose a digest, so `digest` is null. An unavailable endpoint produces an error with an empty model list; it does not prove that no models are installed.

Only loopback HTTP origins with an explicit port are accepted. Discovery disables proxies and redirects, uses a two-second timeout, and caps the response at 1 MiB and 1,000 model entries. It sends no request to inference, load, unload, or download endpoints. The tests use fixture responses and do not establish live LM Studio compatibility.

API source: [LM Studio native v1 model listing](https://lmstudio.ai/docs/developer/rest/list).
