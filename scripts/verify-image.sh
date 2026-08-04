#!/usr/bin/env bash
# Inspect a built AeroOS image before it goes near an SD card.
#
#   ./scripts/verify-image.sh output/image/aeroos-rpi4-2026-08-04.img.zst
#
# Checks what is expensive to discover after flashing: that the application and
# its units are present, that the offline dependency set actually installed,
# that the key file has permissions the service user can read, and that the
# actuator master enable is still off.
#
# The system partition is erofs, which the Docker VM kernel cannot mount, so
# this extracts the partition with erofs-utils rather than mounting it. That
# also means the check needs no privileges.
set -euo pipefail

image="${1:-}"
if [ -z "$image" ] || [ ! -f "$image" ]; then
  echo "usage: $0 <image.img or image.img.zst>" >&2
  exit 1
fi

# Guard against the checker itself silently doing nothing.
marker=$(mktemp)
trap 'if ! grep -q done "$marker"; then
        echo "verify-image.sh produced no result — the check did not run" >&2; fi
      rm -f "$marker"' EXIT

dir=$(cd "$(dirname "$image")" && pwd)
docker run --rm -i -v "$dir:/img" -w /img debian:trixie-slim bash -s "$(basename "$image")" <<'INNER'
set -euo pipefail
img="$1"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends erofs-utils fdisk zstd >/dev/null

if [ "${img##*.}" = "zst" ]; then
  echo "=== decompressing ==="
  zstd -d -q -f "$img" -o /tmp/image.img
  img=/tmp/image.img
fi

echo "=== partition table ==="
fdisk -l "$img" | tail -8

# The system partition is the first Linux filesystem entry in the A/B layout.
read -r start count < <(fdisk -l -o Start,Sectors,Type "$img" \
  | awk '/Linux filesystem/ {print $1, $2; exit}')
[ -n "${start:-}" ] || { echo "no Linux filesystem partition found" >&2; exit 1; }

echo "=== extracting system partition (sector $start, $count sectors) ==="
dd if="$img" of=/tmp/sys.erofs bs=512 skip="$start" count="$count" status=none
fsck.erofs --extract=/tmp/sysroot --overwrite /tmp/sys.erofs >/dev/null 2>&1 || true
[ -d /tmp/sysroot ] || { echo "could not extract the system partition" >&2; exit 1; }
r=/tmp/sysroot
fail=0

echo "--- application modules ---"
for f in ai.py network.py diagnostics.py hardware_config.py main.py control.py database.py; do
  if find "$r/opt/aeroos" -name "$f" -print -quit 2>/dev/null | grep -q .; then
    echo "  ok      $f"
  else
    echo "  MISSING $f"; fail=1
  fi
done

echo "--- offline install ---"
if [ -x "$r/opt/aeroos/venv/bin/aeroos" ]; then
  echo "  ok      venv console script"
else
  echo "  MISSING venv console script"; fail=1
fi
# sysv_ipc is source-only and gated on sys_platform == "linux". A wheelhouse
# prepared on a non-Linux host silently omits it, and the DHT22 driver needs it.
if find "$r/opt/aeroos/venv" -name 'sysv_ipc*' -print -quit 2>/dev/null | grep -q .; then
  echo "  ok      sysv_ipc built for aarch64"
else
  echo "  MISSING sysv_ipc — the wheelhouse was built on the wrong platform"; fail=1
fi

echo "--- systemd units ---"
for u in aeroos.service aeroos-kiosk.service aeroos-camera-gate.service; do
  if [ -f "$r/etc/systemd/system/$u" ]; then echo "  ok      $u"; else echo "  MISSING $u"; fail=1; fi
done

echo "--- /etc/aeroos ---"
ls -la "$r/etc/aeroos/" | sed 's/^/  /'
# The service runs as the aeroos user; a root-only key file locks it out at
# start-up, which is a boot failure rather than a missing feature.
if [ -r "$r/etc/aeroos/gemini.env" ]; then
  mode=$(stat -c '%a' "$r/etc/aeroos/gemini.env")
  [ "$mode" = "640" ] && echo "  ok      gemini.env is $mode" \
    || { echo "  WRONG   gemini.env is $mode, expected 640"; fail=1; }
fi

echo "--- safety ---"
if grep -q 'actuator_master_enable *= *false' "$r/etc/aeroos/hardware.toml"; then
  echo "  ok      actuator master enable is off"
else
  echo "  WRONG   actuator master enable is not off"; fail=1
fi

echo "--- assistant ---"
grep -h '^DEFAULT_MODEL' "$(find "$r/opt/aeroos" -name ai.py | head -1)" | sed 's/^/  /'
keys=$(grep -E '^AEROOS_GEMINI_KEYS=' "$r/etc/aeroos/gemini.env" 2>/dev/null \
  | cut -d= -f2- | tr ',' '\n' | grep -c '[^[:space:]]' || true)
if [ "${keys:-0}" -gt 0 ]; then
  echo "  $keys Gemini key(s) baked in — treat this image as a credential"
else
  echo "  empty key template; install keys after flashing"
fi

echo
[ "$fail" = 0 ] && echo "=== image verified ===" || { echo "=== image has problems ==="; exit 1; }
INNER
echo done > "$marker"
