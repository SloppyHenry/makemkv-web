#!/usr/bin/env bash
# Installiert/aktualisiert MakeMKV-Web: Kernelmodule, .env, Docker-Image (neueste MakeMKV-Version), Start.
set -euo pipefail
cd "$(dirname "$0")"

command -v docker >/dev/null || { echo "Docker fehlt (https://docs.docker.com/engine/install/)"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Docker Compose Plugin fehlt"; exit 1; }
SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo"

echo "→ Kernelmodule sg + sr_mod laden und beim Boot aktivieren"
$SUDO modprobe sg sr_mod || true
printf 'sg\nsr_mod\n' | $SUDO tee /etc/modules-load.d/makemkv.conf >/dev/null

if [ ! -f .env ]; then
  cp .env.example .env
  sed -i.bak "s/^PUID=.*/PUID=$(id -u)/; s/^PGID=.*/PGID=$(id -g)/; s/^CDROM_GID=.*/CDROM_GID=$(getent group cdrom | cut -d: -f3 || echo 24)/" .env && rm -f .env.bak
  echo "→ .env angelegt – bei Bedarf anpassen (Ausgabeordner, Port)"
fi
set -a; . ./.env; set +a
mkdir -p data
[ -d "${NAS_MOUNT:-/mnt/nas}" ] || { echo "→ Lege ${NAS_MOUNT:-/mnt/nas} an"; $SUDO mkdir -p "${NAS_MOUNT:-/mnt/nas}"; }

if [ "${ACCEPT_EULA:-}" != "yes" ]; then
  echo
  echo "MakeMKV ist proprietäre Software. Bitte die EULA lesen: https://www.makemkv.com/eula/"
  read -r -p "EULA akzeptieren und MakeMKV von makemkv.com herunterladen/bauen? [j/N] " a
  [[ "$a" =~ ^[jJyY] ]] || { echo "Abgebrochen."; exit 1; }
fi
export ACCEPT_EULA=yes

echo "→ Baue Image (lädt die neueste MakeMKV-Version) …"
docker compose build --pull
docker compose up -d
echo "→ MakeMKV-Version im Image: $(docker run --rm --entrypoint cat makemkv-web /etc/makemkv-version)"
echo "Fertig: http://$(hostname -I 2>/dev/null | awk '{print $1}'):${PORT:-8780}"
