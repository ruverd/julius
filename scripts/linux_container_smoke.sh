#!/bin/sh
# Optional local Linux-arm64 validation. Does not install Docker for Julius users.
set -eu
cd "$(dirname "$0")/.."
docker run --rm --platform linux/arm64 \
  --mount "type=bind,source=$PWD,target=/src" \
  --workdir /src \
  --env CARGO_TARGET_DIR=/tmp/julius-target \
  rust:1.98-bookworm sh scripts/linux_container_inner.sh
