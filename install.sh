#!/usr/bin/env bash
# Installs/updates Spindle: kernel modules, .env, Docker image (latest MakeMKV version), start.
set -euo pipefail
cd "$(dirname "$0")"

command -v docker >/dev/null || { echo "Docker is missing (https://docs.docker.com/engine/install/)"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Docker Compose plugin is missing"; exit 1; }
SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo -n"      # no password prompt; the root parts are handled by scripts/setup-host.sh

echo "→ Loading kernel modules sg + sr_mod and enabling them at boot"
{ $SUDO modprobe sg sr_mod && printf 'sg\nsr_mod\n' | $SUDO tee /etc/modules-load.d/makemkv.conf >/dev/null; } 2>/dev/null \
  || echo "   (skipped – no root privileges; run sudo ./scripts/setup-host.sh once)"

if [ ! -f .env ]; then
  cp .env.example .env
  sed -i.bak "s/^PUID=.*/PUID=$(id -u)/; s/^PGID=.*/PGID=$(id -g)/; s/^CDROM_GID=.*/CDROM_GID=$(getent group cdrom | cut -d: -f3 || echo 24)/; s/^RENDER_GID=.*/RENDER_GID=$(getent group render | cut -d: -f3 || echo 105)/" .env && rm -f .env.bak
  echo "→ .env created – adjust if needed (output folder, port)"
fi
grep -q "^INSTANCE_NAME=" .env || echo "INSTANCE_NAME=$(hostname)" >> .env    # name of this instance (used in lock files)
grep -q "^RENDER_GID=" .env || echo "RENDER_GID=$(getent group render | cut -d: -f3 || echo 105)" >> .env   # group render (hardware encoding via /dev/dri)
# NVIDIA card (NVENC): include docker-compose.nvidia.yml if Docker knows the card via CDI; NVIDIA=no in .env turns it off
nvidia_cdi() {   # read everything first: grep -q in a pipe would abort with SIGPIPE under pipefail
  local out
  out="$( { command -v nvidia-ctk >/dev/null && nvidia-ctk cdi list 2>/dev/null; cat /etc/cdi/*.yaml /var/run/cdi/*.yaml 2>/dev/null; } || true)"
  [[ "$out" == *nvidia.com/gpu* ]]
}
want_nvidia="$(sed -n 's/^NVIDIA=//p' .env | tail -1)"
sed -i.bak '/^COMPOSE_FILE=/d' .env && rm -f .env.bak
if [ "${want_nvidia:-auto}" != "no" ] && nvidia_cdi; then
  echo "COMPOSE_FILE=docker-compose.yml:docker-compose.nvidia.yml" >> .env
  echo "→ NVIDIA card found – passing it through to the container (NVENC)"
elif [ "${want_nvidia:-auto}" = "yes" ]; then
  echo "   NVIDIA=yes, but Docker does not know any NVIDIA card (CDI) – install the NVIDIA Container Toolkit"
fi
set -a; . ./.env; set +a
mkdir -p data "${STAGING_PATH:-data/staging}"
[ -d "${NAS_MOUNT:-/mnt/nas}" ] || { echo "→ Creating ${NAS_MOUNT:-/mnt/nas}"; $SUDO mkdir -p "${NAS_MOUNT:-/mnt/nas}" 2>/dev/null || echo "   (folder is missing – run sudo ./scripts/setup-host.sh once)"; }

if [ "${ACCEPT_EULA:-}" != "yes" ]; then
  echo
  echo "MakeMKV is proprietary software. Please read the EULA: https://www.makemkv.com/eula/"
  read -r -p "Accept the EULA and download/build MakeMKV from makemkv.com? [y/N] " a
  [[ "$a" =~ ^[yYjJ] ]] || { echo "Aborted."; exit 1; }
fi
export ACCEPT_EULA=yes

# do not abort a running rip by restarting the container
if [ "${FORCE:-0}" != "1" ] && curl -fs -m 5 "http://localhost:${PORT:-8780}/api/state" 2>/dev/null | grep -qE '"job": ?\{'; then
  echo "A rip/scan is running right now. An update would abort it."
  echo "Run again later, or force it with FORCE=1 ./install.sh."
  exit 1
fi

# Rename makemkv-web → spindle: replace the old container (data lives in ./data and is kept)
docker rm -f makemkv-web >/dev/null 2>&1 && echo "→ Removed old container makemkv-web" || true

echo "→ Building image (fetches the latest MakeMKV version) …"
docker compose build --pull
docker compose up -d
echo "→ MakeMKV version in the image: $(docker run --rm --entrypoint cat spindle /etc/makemkv-version)"
echo "Done: http://$(hostname -I 2>/dev/null | awk '{print $1}'):${PORT:-8780}"
