#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

if [ ! -f .venv/bin/python ]; then
  printf '%s\n' 'Run sh scripts/dev.sh setup before building a standalone executable.' >&2
  exit 2
fi

# Build on each target platform; PyInstaller does not cross-compile.
uv run --no-sync --with 'pyinstaller==6.22.3' pyinstaller \
  --clean --noconfirm --onefile --console \
  --name julius \
  --add-data "$PWD/python/julius/data/repo_task_pilot.json:julius/data" \
  --distpath dist/standalone \
  --workpath dist/pyinstaller-work \
  --specpath dist/pyinstaller-spec \
  scripts/standalone_entry.py

uv run --no-sync python scripts/standalone_smoke.py dist/standalone/julius
