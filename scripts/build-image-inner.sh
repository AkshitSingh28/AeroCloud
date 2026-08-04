#!/usr/bin/env bash
# Runs inside the privileged arm64 Debian container. See build-image-docker.sh.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
gen_dir=/opt/rpi-image-gen
staging_root=/tmp/aeroos-build
staging=/tmp/aeroos-build/image

echo "=== installing build dependencies ==="
apt-get update -qq
# rpi-image-gen compiles some of its host tools (erofs-utils, genimage) from
# source, so this needs the headers those builds link against, not just the
# runtime packages.
apt-get install -y -qq --no-install-recommends \
  git ca-certificates sudo bc python3 python3-pip xz-utils zstd file kmod \
  build-essential pkg-config autoconf automake libtool \
  zlib1g-dev liblzma-dev libzstd-dev liblz4-dev libssl-dev uuid-dev \
  libselinux1-dev libconfuse-dev libarchive-dev libcurl4-openssl-dev \
  fdisk gawk python3-dev python3-venv >/dev/null

echo "=== fetching rpi-image-gen ==="
# The directory is bind-mounted, so it exists but may be empty on a first run.
if [ ! -e "$gen_dir/rpi-image-gen" ]; then
  git clone --depth 1 https://github.com/raspberrypi/rpi-image-gen /tmp/rig
  cp -a /tmp/rig/. "$gen_dir/"
  rm -rf /tmp/rig
fi
cd "$gen_dir"
git log --oneline -1

if [ -x ./install_deps.sh ]; then
  ./install_deps.sh
else
  echo "install_deps.sh missing; installing the documented package set" >&2
  apt-get install -y -qq --no-install-recommends \
    bdebstrap mmdebstrap genimage dosfstools e2fsprogs \
    qemu-user-static binfmt-support systemd-container \
    pigz uuid-runtime crudini rsync >/dev/null
fi

# The wheelhouse is rebuilt here, natively, rather than trusted from the host.
# `pip download --platform` still evaluates environment markers against the
# machine running pip, so preparing it on macOS silently drops every dependency
# gated on sys_platform == "linux" — adafruit-blinka needs sysv_ipc, which is
# source-only, and the image then fails to install the application offline.
# Building in an arm64 Linux container gets the markers right and turns any
# sdist into a real aarch64 wheel.
echo "=== rebuilding the offline wheelhouse (native arm64 linux) ==="
wheelhouse=/work/image/assets/wheelhouse
rm -rf "$wheelhouse"
mkdir -p "$wheelhouse"
python3 -m venv /tmp/wheelbuilder
/tmp/wheelbuilder/bin/pip install -q --upgrade pip wheel
/tmp/wheelbuilder/bin/pip wheel --wheel-dir "$wheelhouse" "hatchling>=1.26" >/dev/null
/tmp/wheelbuilder/bin/pip wheel --wheel-dir "$wheelhouse" "/work[pi]" >/dev/null
echo "  $(ls "$wheelhouse" | wc -l) wheels"
# The offline install has no fallback, so prove the set actually resolves.
python3 -m venv /tmp/wheelcheck
/tmp/wheelcheck/bin/pip install -q --no-index --find-links="$wheelhouse" "/work[pi]"
echo "  offline install resolves"
rm -rf /tmp/wheelbuilder /tmp/wheelcheck

# Stage the image definition so a --with-keys build never edits the repository.
# The config resolves deploy/ and scripts/ as ${@SRCROOT}/../, so the staging
# directory has to sit inside a tree with the same shape as the project.
rm -rf "$staging_root"
mkdir -p "$staging_root"
cp -a /work/image "$staging"
ln -s /work/deploy "$staging_root/deploy"
ln -s /work/scripts "$staging_root/scripts"
if [ "${WITH_KEYS:-0}" = "1" ]; then
  echo "=== baking Gemini keys into the image ==="
  cp /work/deploy/gemini.env "$staging/gemini.env"
  sed -i 's|gemini_example: .*|gemini_example: ${@SRCROOT}/gemini.env|' "$staging/config/aeroos.yaml"
fi

echo "=== building ==="
./rpi-image-gen build -S "$staging" -c aeroos.yaml

echo "=== collecting artefacts ==="
# Only the deploy directory. A wildcard over the whole rpi-image-gen tree picks
# up util-linux's filesystem test fixtures, which are also called *.img.
out=/work/output/image
mkdir -p "$out"
deploy=$(ls -d "$gen_dir"/work/deploy-* 2>/dev/null | head -1)
[ -n "$deploy" ] || { echo "no deploy directory found" >&2; exit 1; }

stamp=$(date +%Y-%m-%d)
suffix=""
[ "${WITH_KEYS:-0}" = "1" ] && suffix="-withkeys"
name="aeroos-rpi4-${stamp}${suffix}"

cp -v "$deploy/aeroos-rpi4.img.zst" "$out/$name.img.zst"
for extra in deployed.json image.json.zst manifest.zst filesystem-*.sbom.zst; do
  [ -e "$deploy/$extra" ] && cp "$deploy/$extra" "$out/$name.$(basename "$extra")" || true
done

cd "$out"
sha256sum "$name.img.zst" > "$name.sha256"
echo
echo "Image:  $out/$name.img.zst"
echo "Size:   $(du -h "$name.img.zst" | cut -f1) compressed"
cat "$name.sha256"
