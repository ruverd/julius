# Local standalone release

The local standalone archive contains a Julius executable, its SHA-256 manifest, and the offline installer script. Each archive is built for one exact operating system and machine architecture. It is unsigned and is not a published release.

Build on the target machine after the standalone build:

```sh
sh scripts/build_standalone.sh
python3 scripts/package_standalone.py --version 0.2.0 --output dist/julius-0.2.0-darwin-arm64.tar.gz
```

Inspect the manifest and install into `~/.local`:

```sh
python3 scripts/install_standalone.py install --archive dist/julius-0.2.0-darwin-arm64.tar.gz
python3 scripts/install_standalone.py install --archive dist/julius-0.2.0-darwin-arm64.tar.gz --apply
~/.local/bin/julius --help
```

The first command only previews. `--apply` is required for every change. Use `--prefix PATH` to select another directory. `update --archive NEW_ARCHIVE`, `rollback`, and `remove` follow the same preview/apply convention. Updates save the prior executable under `.julius-backups`; rollback restores the most recent prior version. Repeated updates to the same version, rollback with no history, and remove with no managed installation make no changes.

The installer verifies archive hashes and the current platform and architecture. It refuses to replace an unrelated binary, symlink, or modified managed binary. The managed state file is `.julius-install.json` within the prefix. Keep the state file and backup directory with the install if you want update and rollback. All operations use local files; the installer downloads nothing.

This archive and installer were tested locally on macOS arm64. Linux, WSL, and Windows builds and installation remain untested. Build and test a separate archive on each target. Code signing, notarization, and published distribution are separate release gates.
