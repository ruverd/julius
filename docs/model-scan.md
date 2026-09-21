# Local model scan

`scan_models(registry, provider=..., endpoint=...)` is an explicit bridge from the existing Ollama or LM Studio read-only discovery functions to the append-only model registry. It calls only the selected local discovery endpoint, then stores one snapshot for each model returned. Discovery itself enforces loopback URLs, blocks redirects, and does not download, load, or run a model.

The scan records the model name, digest and quantization when present, plus `loaded` or `installed` state. If loaded status is unknown, a listed installed model remains `installed`. The scan leaves responded model, alias, tokenizer, template, context window, tool capabilities, and source update timestamp unknown. It does not infer those fields from a display name or model tag. An unavailable endpoint returns an error and zero new model snapshots; it does not fabricate an `unavailable` model.

Every scan appends new observations. The endpoint is part of model identity, so identically named models on different local servers remain distinct. These observations describe local discovery output, not live inference compatibility or hardware fitness.

The registry creates its database with owner-only permissions and rejects a direct symlink or an existing database readable by other users. It leaves an unsafe existing file untouched.
