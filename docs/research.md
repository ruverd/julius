# Julius research notes

Sources verified 2026-10-21. Design inspiration only; no third-party source copied.

| Project | Inspected implementation | Applicable idea | Limitation |
|---|---|---|---|
| [minRLM](https://github.com/avilum/minrlm) | minrlm/core.py PythonREPL._search/_peek/execute and RLM.completion | Keep large context outside prompt, retrieve small slices on demand | General exec plus model control loop is not automatic cost reduction; avoid arbitrary runtime here |
| [codemode-lite](https://github.com/redhat-et/codemode-lite) | codemode/engine.py CodeMode._build_discovery_helpers and MCP adapter | Discover operation summaries, load one schema when required, batch bounded operations | Runs Python with Podman/Pyodide backends; import denylist alone is not a security boundary. Julius chooses constrained operations |
| [RecursiveMAS](https://github.com/RecursiveMAS/RecursiveMAS) | inference/modeling.py Adapter/CrossModelAdapter nn.Module | Reuse intermediate work between agents | Requires model hidden-state access/training. Not available through ordinary commercial text APIs |
| [ReCache](https://github.com/EIT-NLP/ReCache) | README model/training/evaluation contract | Resource-level independence for cache reuse | Custom attention on Qwen models, KV memory reduction is not billed-token reduction; final Inv-F1 lower than dense in own results |
| [EfficientAgent](https://github.com/KunmingSHAO/efficientagent_release) | README KV host-tier sizing/admission and repository structure | Retain reusable context based on working-set pressure | vLLM/LMCache deployment optimization, not client API token compression |

## Product hypothesis
A local content-addressed context store with short previews, exact recovery and explicit budgets can lower visible tool output without model access. A small discovery/call MCP interface can lower initial schema overhead. Both must account for discovery, wrappers, searches and later full retrieval. Full retrieval may erase savings, which must remain visible.

## Measurement
Offline fixed-fixture benchmarks prove payload accounting, retained fixture facts and recovery, not end-to-end coding success or API invoice savings. Report named tokenizer/estimator and upstream source SHA. No generic 90% claim. Real task trials require matched task/model/agent setup, outcome checks and provider usage including cached and uncached input, output and all retries.

## Source identities
Trail-Code source commit b1211efd3eef0efa121b93800e5dd8e547aead77.
minRLM core blob fca62e81a8fb60fb306b3c1e81a16b0b58278984.
codemode-lite engine blob c4f9efa58a65336daaeb0915753b95619023a460.
RecursiveMAS modeling blob 1bde67f635005121892e297055d83462b2f762f0.
ReCache README blob 54111479ed5875d7db626598132f328775c9c726.
EfficientAgent README blob 942bd7b6bb9f047fdebd6c81d060e12a71aac77b.
