#!/usr/bin/env bash
# Updates an existing installation: backs up .env and data/*.json, remembers the current state for rollback,
# fetches the new state (git pull) and rebuilds/restarts (install.sh).
# install.sh asks for the MakeMKV EULA; if you already know it, set ACCEPT_EULA=yes yourself.
#   ./scripts/update.sh                 default (aborts if a rip/scan is running)
#   FORCE=1 ./scripts/update.sh         even while a rip is running
#   ./scripts/update.sh rollback        back to the state remembered before the last update
set -euo pipefail
cd "$(dirname "$0")/.."
BACKUPS=../spindle-backups
[ -d ../makemkv-web-backups ] && [ ! -e "$BACKUPS" ] && mv ../makemkv-web-backups "$BACKUPS"   # old name
mkdir -p "$BACKUPS"

if [ "${1:-}" = "rollback" ]; then
  [ -f "$BACKUPS/letzter-stand.txt" ] || { echo "No remembered state in $BACKUPS/letzter-stand.txt"; exit 1; }
  old="$(cat "$BACKUPS/letzter-stand.txt")"
  echo "→ Back to $old"
  git checkout -q "$old"
  ./install.sh
  echo "Done. The backup of .env/data is in $BACKUPS (copy it back by hand if needed)."
  exit 0
fi

git diff --quiet && git diff --cached --quiet || { echo "There are local changes – please sort them out first (git status)."; exit 1; }
port="$(sed -n 's/^PORT=\([0-9]*\).*/\1/p' .env | head -1)"
if [ "${FORCE:-0}" != "1" ] && curl -fs -m 5 "http://localhost:${port:-8780}/api/state" 2>/dev/null | grep -qE '"job": ?\{'; then
  echo "A rip/scan is running right now – run again later (or FORCE=1)."; exit 1
fi

stamp="$(date +%Y%m%d-%H%M%S)"
git rev-parse HEAD > "$BACKUPS/letzter-stand.txt"
tar -czf "$BACKUPS/sicherung-$stamp.tgz" .env $(ls data/*.json 2>/dev/null)
echo "→ Backed up: $BACKUPS/sicherung-$stamp.tgz (previous state: $(git rev-parse --short HEAD))"

git fetch -q origin
git checkout -q main
git pull --ff-only origin main
echo "→ New state: $(git rev-parse --short HEAD)"
./install.sh
