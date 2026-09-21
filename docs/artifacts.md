# Artifact exports

`ArtifactStore.export(project_id, destination, artifact_ids, *, authorized=True)`
exports selected, unexpired originals from one project. The caller must obtain
the user's authorization for each export and pass `authorized=True`. The method
does not infer authorization from filesystem access. It creates a new private
directory and rejects an existing destination.

The default export writes only `manifest.json`. It lists each artifact's ID,
project ID, byte count, SHA-256 digest, creation time, and expiration time. It
does not include original content. Set `include_raw=True` only when the user
explicitly requests the original text. Raw files use artifact IDs as filenames,
and the manifest maps each entry to its file. The manifest digest covers the
exact UTF-8 bytes of that file.

Before writing anything, export checks project membership, expiration, stored
file permissions, size, and SHA-256 integrity. It accepts 1–32 distinct artifact
IDs and at most 16 MiB total original content. Missing or invalid artifacts
abort the export. The destination must not be a symlink, and created files use
owner-only permissions. Treat raw exports as sensitive data; remove them when
they are no longer needed.
