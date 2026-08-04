#!/usr/bin/env bash
set -euo pipefail

gate_dir=/var/lib/aeroos/camera-gate
mkdir -p "$gate_dir"

list_output="$gate_dir/cameras.txt"
stream_file="$gate_dir/live-1080p.h264"
still_file="$gate_dir/still-64mp.jpg"

rpicam-hello --list-cameras > "$list_output" 2>&1
if ! grep -Eiq 'arducam|b0483|9152x6944' "$list_output"; then
  echo "AeroOS camera gate: Arducam B0483 / 64MP mode did not enumerate" >&2
  exit 20
fi

rpicam-vid --timeout 2500 --width 1920 --height 1080 --framerate 15 \
  --autofocus-mode continuous --nopreview --output "$stream_file"
test -s "$stream_file"

rpicam-still --timeout 5000 --width 9152 --height 6944 \
  --autofocus-on-capture --nopreview --output "$still_file"
test -s "$still_file"

date -u +%Y-%m-%dT%H:%M:%SZ > "$gate_dir/passed-at"
