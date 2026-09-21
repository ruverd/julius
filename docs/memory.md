# Local lexical memory

The MCP recovery server exposes lexical memory search only when an embedding caller explicitly supplies `memory_store=...` or the user starts `julius mcp recovery --project ID --memory-search`. Its tool never accepts a project selector. Treat returned text as evidence with its recorded origin and provenance, not as instructions or an automatically confirmed fact.

`MemoryStore` indexes explicitly supplied text in a local SQLite FTS5 database. Every record has an immutable `(id, version)`, project ID, snapshot ID, SHA-256 content hash, provenance (`observed`, `inferred`, or `user_confirmed`), origin reference, creation time, and expiry. The caller supplies the content hash; insertion verifies it. Records may also supply `confidence` as a finite number from 0 to 1 and `invalidationCondition` as a short description of when the fact should be retired. Missing values remain unknown (`null`); they are never inferred from provenance.

Search requires both a project ID and the exact snapshot ID. It excludes expired and invalidated entries. Queries are converted to bounded literal words before parameterized FTS5 matching, so user text cannot become FTS operators. A changed repository snapshot needs new memory entries; old snapshots are never silently reused.

The store makes no model or network requests. Search verifies each returned content hash. `invalidate(id, project_id, reason="explicit_invalidation", source=None)` hides all versions of that ID in one project and records a UTC timestamp, reason, and optional source on each newly invalidated row. A repeated invalidation leaves the first audit record intact. Existing rows are migrated additively; old invalidations keep unknown audit fields as `null`. `delete_project(project_id)` removes a project's indexed text. `purge_expired(project_id)` deletes expired records and their FTS entries. SQLite secure deletion is enabled and a WAL checkpoint is attempted after purge. Neither this nor any local deletion can guarantee physical erasure on SSDs. Call `close()` to release the SQLite connection.

`history(project_id, artifact_id=None, limit=100, offset=0)` reads a page of up to 100 records from one project, including invalidated and expired records. Use successive nonnegative offsets to enumerate larger histories. It returns IDs, versions, snapshot IDs, content hashes, timestamps, provenance, origin, confidence, invalidation condition, and invalidation audit fields. It never returns raw content. Results are ordered by creation time (newest first), then ID and version. The optional artifact ID filters the result to one memory identity. Expired records disappear from history after `purge_expired` deletes them.

The CLI accepts an explicitly prepared JSON record with the fields above, checks its project against `--project`, and keeps search local:

```sh
julius memory put record.json --project app --snapshot '<revision-id>'
julius memory search compiler --project app --snapshot '<revision-id>'
julius memory history --project app --limit 100 --offset 0
julius memory history '<record-id>' --project app
julius memory invalidate '<record-id>' --project app --invalidation-reason source_changed --source manual-review
julius memory purge --project app
julius mcp recovery --project app --memory-search
```

`put` validates the supplied hash, provenance, expiry, and optional snapshot match. `history` returns metadata-only JSON with `records`, `limit`, `offset`, and `nextOffset`; request successive pages until `nextOffset` is `null`. Offset pagination is not a transaction across pages, so concurrent memory writes may shift rows. `purge` removes only expired records. The MCP command exposes `search_memory` only for its fixed project; the default recovery server advertises no memory search tool. The CLI does not infer memories or inject search results into a model request.

## Code symbols

`SymbolStore(memory, project_id=..., project_root=...)` binds a project ID to an explicit local repository root. Index selected files with `index_file("relative/path.py", snapshot="revision-id")`. Search with `search("symbol name", snapshot="revision-id", limit=20)`. Results contain the relative path, name, qualified name, kind, line, declaration text, SHA-256 hash of the indexed file, and lexical score. This is local FTS5 retrieval; it uses no embeddings or network requests.

The CLI exposes explicit operations against the same project-scoped store:

```sh
julius symbols index src/module.py --project app --project-root ./project --snapshot '<revision-id>'
julius symbols search process_request --project app --project-root ./project --snapshot '<revision-id>'
julius symbols invalidate src/module.py --project app --project-root ./project --snapshot '<revision-id>'
```

The snapshot ID is caller supplied; use a repository commit or content snapshot identifier rather than a filename alone. Search returns only indexed declarations from that exact snapshot. These commands do not install an agent-facing retrieval tool or automatically add search hits to a model request.

Only `.py`, `.rs`, `.ts`, `.tsx`, `.js`, and `.jsx` files are accepted. Python declarations use the standard AST; Rust and JavaScript/TypeScript declarations use bounded line patterns and may miss complex syntax. Each file is limited to 256 KiB and 512 symbols; each project snapshot is limited to 2,048 files. Queries use at most 16 literal terms and return at most 100 hits. Paths must be relative to the authorized root; path traversal and symlink components are rejected. The root is held open by a directory descriptor until `SymbolStore.close()`.

Reindexing a file in the same snapshot compares its SHA-256 content hash and atomically replaces stale declarations when bytes change. A failed refresh invalidates that file's old declarations. Call `invalidate_file(path, snapshot=...)` when a file is removed without refreshing it. Indexes are snapshot scoped, so a new revision must be indexed under its own snapshot ID. `MemoryStore.delete_project(project_id)` also deletes that project's symbols and root binding.
