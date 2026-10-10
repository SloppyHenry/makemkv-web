#!/usr/bin/env bash
# Aktualisiert eine vorhandene Installation: sichert .env und data/*.json, merkt sich den Stand für den Rückweg,
# holt den neuen Stand (git pull) und baut/startet neu (install.sh).
# Die MakeMKV-EULA fragt install.sh ab; wer sie schon kennt, setzt ACCEPT_EULA=yes selbst.
#   ./scripts/update.sh                 Standard (bricht ab, wenn gerade ein Rip/Scan läuft)
#   FORCE=1 ./scripts/update.sh         auch bei laufendem Rip
#   ./scripts/update.sh rollback        zurück auf den vor dem letzten Update gemerkten Stand
set -euo pipefail
cd "$(dirname "$0")/.."
BACKUPS=../makemkv-web-backups
mkdir -p "$BACKUPS"

if [ "${1:-}" = "rollback" ]; then
  [ -f "$BACKUPS/letzter-stand.txt" ] || { echo "Kein gemerkter Stand in $BACKUPS/letzter-stand.txt"; exit 1; }
  old="$(cat "$BACKUPS/letzter-stand.txt")"
  echo "→ Zurück auf $old"
  git checkout -q "$old"
  ./install.sh
  echo "Fertig. Die Sicherung von .env/data liegt in $BACKUPS (bei Bedarf von Hand zurückkopieren)."
  exit 0
fi

git diff --quiet && git diff --cached --quiet || { echo "Es gibt lokale Änderungen – bitte erst klären (git status)."; exit 1; }
port="$(sed -n 's/^PORT=\([0-9]*\).*/\1/p' .env | head -1)"
if [ "${FORCE:-0}" != "1" ] && curl -fs -m 5 "http://localhost:${port:-8780}/api/state" 2>/dev/null | grep -qE '"job": ?\{'; then
  echo "Es läuft gerade ein Rip/Scan – später erneut ausführen (oder FORCE=1)."; exit 1
fi

stamp="$(date +%Y%m%d-%H%M%S)"
git rev-parse HEAD > "$BACKUPS/letzter-stand.txt"
tar -czf "$BACKUPS/sicherung-$stamp.tgz" .env $(ls data/*.json 2>/dev/null)
echo "→ Gesichert: $BACKUPS/sicherung-$stamp.tgz (Stand vorher: $(git rev-parse --short HEAD))"

git fetch -q origin
git checkout -q main
git pull --ff-only origin main
echo "→ Neuer Stand: $(git rev-parse --short HEAD)"
./install.sh
