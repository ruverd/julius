# Local standalone release

The local standalone archive contains a Julius executable, its SHA-256 manifest, and the offline installer script. Each archive is built for one operating system and machine architecture. The executable bundles Python and does not need a separate Python runtime to run. The installer is a Python 3.10+ script, so installing from this archive still requires Python or manual copying. This artifact has no Developer ID signature or notarization and is not a published release. A manifest hash detects accidental archive changes but does not authenticate its publisher.

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

The macOS arm64 executable passed an offline smoke test for its CLI version, bundled subprocess dispatch, hook candidate, MCP initialize/list, artifact restoration, and lexical memory search. It also ran from a temporary directory with `PATH=/usr/bin:/bin` and no `PYTHONPATH`. The archive was installed into a temporary prefix, launched, then removed. This checks one local machine, not a clean-machine release.

An optional [Linux arm64 container validation script](../scripts/linux_container_smoke.sh) builds the wheel and standalone executable in `rust:1.98-bookworm` with Python 3.11, runs the Python/Rust checks and standalone smoke, creates `dist/julius-0.2.0-linux-aarch64.tar.gz`, and tests a temporary install/remove. This is development validation only: Julius does not require Docker to install or run. The container checks Debian Bookworm/glibc 2.36 on Linux arm64; native Linux hosts, other distributions/architectures, WSL, and Windows remain untested. The [standalone CI workflow](../.github/workflows/standalone.yml) specifies macOS and Linux builds but has not run remotely in this task. Build and test a separate archive on each target. Code signing, notarization, trusted update distribution, and published distribution remain release gates.

[PyInstaller's operating-mode documentation](https://pyinstaller.org/en/stable/operating-mode.html) describes the bundled interpreter and platform-specific output. Its [usage documentation](https://pyinstaller.org/en/stable/usage.html) recommends building and testing on each target environment; this script uses PyInstaller `6.22.3` and does not cross-compile.
