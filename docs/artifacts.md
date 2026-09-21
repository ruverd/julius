# Artifact exports

`julius artifacts delete-project --project ID` exposes project-wide original deletion through the CLI. It returns `removedArtifacts` and `leftovers` as JSON; nonempty leftovers make the command exit with status 2. Run it separately from event and memory deletion.

`ArtifactStore.delete_project(project_id)` removes verified originals and metadata
from that project's artifact directory. It returns `{"removedArtifacts": count,
"leftovers": [filenames...]}` and is idempotent. It checks every directory
entry before deleting: unexpected names, symlinks, and unsafe file types or
permissions cause a clear error without deleting any entries. A body without
metadata, or a pair with invalid metadata, is left in place and reported as a
leftover because its project membership cannot be verified. A valid metadata
file without its body is removed. Deletion does not follow symlinks and does
not touch another project's directory.

Deletion removes active artifact files only. It does not erase prior exports,
filesystem or SQLite backups, snapshots, or SQLite WAL data. A deleted original
cannot be restored or recounted by Julius from the artifact store; existing
ledger measurements remain historical records.

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

CLI: `julius artifacts export '<artifact-id>' --project app --output ./private-export` creates a metadata-only export. Add `--include-originals` only when you want original text in that new private directory. The explicit export command supplies the library authorization flag; another process cannot export merely by querying a report. The CLI prints the manifest, never the original text.

Before writing anything, export checks project membership, expiration, stored
file permissions, size, and SHA-256 integrity. It accepts 1–32 distinct artifact
IDs and at most 16 MiB total original content. Missing or invalid artifacts
abort the export. The destination must not be a symlink, and created files use
owner-only permissions. Parent symlinks and `..` path traversal are rejected.
On a write failure, cleanup removes only files created by that export. Treat
raw exports as sensitive data; remove them when
they are no longer needed.
