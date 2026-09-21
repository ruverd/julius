#!/bin/sh
# Optional release validation inside rust:1.98-bookworm, not a Julius runtime dependency.
set -eu

apt-get update -qq
apt-get install -y -qq --no-install-recommends python3-venv python3-pip libpython3.11 patchelf

python3 -m venv /tmp/julius-venv
/tmp/julius-venv/bin/pip install --disable-pip-version-check \
  'maturin>=1.9,<2' 'pyinstaller==6.22.3' 'pydantic>=2.11,<3' \
  'pytest>=8,<10' 'ruff>=0.12' 'mypy>=1.15'

/tmp/julius-venv/bin/maturin build --release \
  --manifest-path crates/julius-py/Cargo.toml \
  --interpreter /tmp/julius-venv/bin/python \
  --out /tmp/julius-wheels
/tmp/julius-venv/bin/pip install --disable-pip-version-check /tmp/julius-wheels/*.whl

/tmp/julius-venv/bin/pytest -q -o pythonpath= tests/python
/tmp/julius-venv/bin/ruff check python tests/python scripts
/tmp/julius-venv/bin/mypy python/julius
cargo test --workspace --locked

/tmp/julius-venv/bin/pyinstaller --clean --noconfirm --onefile --console \
  --name julius --distpath /tmp/julius-dist \
  --workpath /tmp/julius-pyinstaller-work \
  --specpath /tmp/julius-pyinstaller-spec scripts/standalone_entry.py
/tmp/julius-venv/bin/python scripts/standalone_smoke.py /tmp/julius-dist/julius

version=$(python3 -c 'import pathlib, tomllib; print(tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["version"])')
archive="dist/julius-$version-linux-aarch64.tar.gz"
python3 scripts/package_standalone.py \
  --binary /tmp/julius-dist/julius --version "$version" \
  --output "$archive"
python3 scripts/install_standalone.py install \
  --archive "$archive" \
  --prefix /tmp/julius-installed --apply
/tmp/julius-installed/bin/julius --version
python3 scripts/install_standalone.py remove \
  --prefix /tmp/julius-installed --apply
