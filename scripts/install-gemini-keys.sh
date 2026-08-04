#!/usr/bin/env bash
# Install Gemini API keys onto an AeroOS appliance.
#
#   ./scripts/install-gemini-keys.sh                 # local: this machine is the Pi
#   ./scripts/install-gemini-keys.sh aeroos@host     # remote: over SSH
#
# The keys go to /etc/aeroos/gemini.env as 0640 root:aeroos. They are
# never passed on a command line — argv is world-readable in /proc while a
# process runs — so the file is copied, not echoed.
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
source_file="$project_dir/deploy/gemini.env"
target="/etc/aeroos/gemini.env"
# 0640 root:aeroos, not 0600 root:root. The control service runs as the aeroos
# user: a file only root can read locks out the one process that needs it, and
# the read happens during start-up.
service_user="aeroos"
remote="${1:-}"

if [ ! -f "$source_file" ]; then
  echo "error: $source_file does not exist." >&2
  echo "       Copy deploy/gemini.env.example to deploy/gemini.env and add your keys." >&2
  exit 1
fi

# Refuse to install an empty file: a silent no-op here looks exactly like a
# working install until the operator wonders why AI is still unavailable.
if ! grep -qE '^AEROOS_GEMINI_KEYS=.+' "$source_file"; then
  echo "error: AEROOS_GEMINI_KEYS is empty in $source_file." >&2
  echo "       Get keys from https://aistudio.google.com/apikey" >&2
  exit 1
fi

count=$(grep -E '^AEROOS_GEMINI_KEYS=' "$source_file" | head -1 | cut -d= -f2- | tr ',' '\n' | grep -c '[^[:space:]]')

if [ -z "$remote" ]; then
  sudo install -D -m 0640 -o root -g "$service_user" "$source_file" "$target"
  sudo systemctl restart aeroos
  echo "Installed $count key(s) to $target and restarted aeroos."
else
  # Land it in the caller's home first: /etc is not writable by the SSH user,
  # and scp cannot elevate.
  scp -q "$source_file" "$remote:/tmp/aeroos-gemini.env"
  ssh "$remote" "sudo install -D -m 0640 -o root -g $service_user /tmp/aeroos-gemini.env $target \
    && rm -f /tmp/aeroos-gemini.env \
    && sudo systemctl restart aeroos"
  echo "Installed $count key(s) to $remote:$target and restarted aeroos."
fi

echo "Now turn AI on in Settings → AI assistance. It stays off until you do."
