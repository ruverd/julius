#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ -x .tools/cargo/bin/cargo ]; then
  export RUSTUP_HOME="$PWD/.tools/rustup"
  export CARGO_HOME="$PWD/.tools/cargo"
  export PATH="$PWD/.tools/cargo/bin:$PATH"
fi
case "${1:-help}" in
  setup) uv sync --frozen ;;
  test)
    uv run --no-sync pytest -q
    uv run --no-sync ruff check python tests/python scripts/wheel_smoke.py
    uv run --no-sync mypy python/julius
    cargo test --workspace --locked
    ;;
  build) uv run --no-sync maturin build --release --interpreter .venv/bin/python --out dist/wheels ;;
  *) printf '%s\n' 'Usage: sh scripts/dev.sh setup|test|build' ;;
esac
