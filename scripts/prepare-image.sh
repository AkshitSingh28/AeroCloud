#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
assets_dir="$project_dir/image/assets"
target_platform="manylinux2014_aarch64"
target_python="3.13"
target_abi="cp313"

mkdir -p "$assets_dir/wheelhouse"
npm --prefix "$project_dir/ui" run build
python3 "$project_dir/scripts/make_splash.py" "$assets_dir/aeroos-splash.tga"
test -f "$project_dir/deploy/hardware.toml"
test -x "$project_dir/scripts/verify-camera.sh"
# The application is installed offline inside the image. Include the PEP 517
# backend as well as runtime dependencies so pip can build the local project
# without reaching PyPI from the chroot.
python3 -m pip download \
  --dest "$assets_dir/wheelhouse" \
  --platform "$target_platform" \
  --python-version "$target_python" \
  --implementation cp \
  --abi "$target_abi" \
  --only-binary=:all: \
  "hatchling>=1.26"
python3 -m pip download \
  --dest "$assets_dir/wheelhouse" \
  --platform "$target_platform" \
  --python-version "$target_python" \
  --implementation cp \
  --abi "$target_abi" \
  --only-binary=:all: \
  "$project_dir[pi]"
# Exclude host bytecode and metadata: the .pyc files are compiled for this
# machine's Python and CPU, and the appliance runs neither. Python ignores them
# on a magic-number mismatch, but they have no business in a release image.
tar -czf "$assets_dir/aeroos-source.tar.gz" \
  --exclude='__pycache__' --exclude='*.py[cod]' --exclude='.DS_Store' \
  -C "$project_dir" aeroos pyproject.toml \
  -C "$project_dir" ui/dist

# A credential must never be baked into an image that gets flashed onto cards
# and handed around. The layer installs the empty template instead.
if grep -qE '^AEROOS_GEMINI_KEYS=.+' "$project_dir/deploy/gemini.env.example"; then
  echo "error: deploy/gemini.env.example contains a key. Templates ship empty." >&2
  exit 1
fi

echo "AeroOS image assets prepared in $assets_dir"
echo "Source tarball: $(tar -tzf "$assets_dir/aeroos-source.tar.gz" | wc -l | tr -d ' ') entries"
