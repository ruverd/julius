# Local lexical memory

`MemoryStore` indexes explicitly supplied text in a local SQLite FTS5 database. Every record has an immutable `(id, version)`, project ID, snapshot ID, SHA-256 content hash, provenance, origin reference, and expiry. The caller supplies the content hash; insertion verifies it.

Search requires both a project ID and the exact snapshot ID. It excludes expired and invalidated entries. Queries are converted to bounded literal words before parameterized FTS5 matching, so user text cannot become FTS operators. A changed repository snapshot needs new memory entries; old snapshots are never silently reused.

The store makes no model or network requests. Search verifies each returned content hash. `invalidate(id, project_id)` hides that ID in one project. `delete_project(project_id)` removes a project's indexed text. `purge_expired(project_id)` deletes expired records and their FTS entries. SQLite secure deletion is enabled and a WAL checkpoint is attempted after purge. Neither this nor any local deletion can guarantee physical erasure on SSDs. Call `close()` to release the SQLite connection.
