#!/usr/bin/env bash
# Build a flashable AeroOS SD-card image inside a privileged arm64 container.
#
#   ./scripts/build-image-docker.sh              # image ships an empty key file
#   ./scripts/build-image-docker.sh --with-keys  # bake deploy/gemini.env in
#
# rpi-image-gen needs an aarch64 Debian host with loop devices, which a Mac is
# not. This runs the supported build inside one. The result lands in output/.
#
# --with-keys puts live credentials inside the .img. That is convenient for a
# chamber you own and a bad idea for an image you intend to share: anyone who
# reads the card reads the keys.
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
with_keys=0
[ "${1:-}" = "--with-keys" ] && with_keys=1

if [ "$with_keys" = 1 ]; then
  if ! grep -qE '^AEROOS_GEMINI_KEYS=.+' "$project_dir/deploy/gemini.env" 2>/dev/null; then
    echo "error: --with-keys needs keys in deploy/gemini.env" >&2
    exit 1
  fi
  echo "NOTE: the built image will contain live Gemini API keys."
fi

# The rpi-image-gen tree lives in a named volume, not a bind mount from the
# host. mmdebstrap drops to the _apt user to download packages, and that user
# cannot write to a macOS-backed filesystem shared into the VM. The volume also
# persists between runs, so the host tools compile once.
mkdir -p "$project_dir/output"
docker volume create aeroos-rpi-image-gen >/dev/null

docker run --rm --privileged \
  -v "$project_dir:/work" \
  -v aeroos-rpi-image-gen:/opt/rpi-image-gen \
  -e WITH_KEYS="$with_keys" \
  -w /work \
  debian:trixie-slim \
  bash /work/scripts/build-image-inner.sh
