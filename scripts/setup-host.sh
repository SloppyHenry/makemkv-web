#!/usr/bin/env bash
# One-time setup of a machine for Spindle – the part that needs root (Debian/Ubuntu):
# Docker + Compose, kernel modules for the drive, target share (NFS) with retry at boot,
# firewall rule for the LAN. Running it several times is harmless.
#
#   sudo NAS_SOURCE=192.0.2.4:/export/data LAN=192.0.2.0/24 ./scripts/setup-host.sh
#
# NAS_SOURCE  NFS source of the output target (empty = do not mount a NAS)
# NAS_MOUNT   mount point (default /mnt/nas)
# LAN         network that may reach the web interface (empty = no firewall rule)
# PORT        port of the web interface (default 8780)
# Afterwards, as a regular user: git clone … && cd spindle && ./install.sh
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Please run with sudo."; exit 1; }
NAS_SOURCE="${NAS_SOURCE:-}"
NAS_MOUNT="${NAS_MOUNT:-/mnt/nas}"
LAN="${LAN:-}"
PORT="${PORT:-8780}"
USER_NAME="${SUDO_USER:-}"
info() { printf '\033[1m==>\033[0m %s\n' "$*"; }

info "Packages: Docker, Compose$([ -n "$NAS_SOURCE" ] && echo ', nfs-common')"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y docker.io docker-compose-v2 ${NAS_SOURCE:+nfs-common}
systemctl enable --now docker
if [ -n "$USER_NAME" ] && ! id -nG "$USER_NAME" | grep -qw docker; then
  usermod -aG docker "$USER_NAME"
  echo "   $USER_NAME is now in the docker group – log in again once (or run 'newgrp docker')."
fi

info "Kernel modules sg + sr_mod (access to optical drives)"
printf 'sg\nsr_mod\n' > /etc/modules-load.d/makemkv.conf
modprobe sg sr_mod 2>/dev/null || true

if [ -n "$NAS_SOURCE" ]; then
  info "Mounting target: $NAS_SOURCE -> $NAS_MOUNT"
  mkdir -p "$NAS_MOUNT"
  grep -qF " $NAS_MOUNT " /etc/fstab || \
    echo "$NAS_SOURCE $NAS_MOUNT nfs4 rw,nofail,_netdev,x-systemd.mount-timeout=20 0 0" >> /etc/fstab
  # At boot the network (Wi-Fi) is often not up yet: retry until it works – and before Docker,
  # so the container can bind the target.
  cat > /etc/systemd/system/makemkv-nas-mount.service <<UNIT
[Unit]
Description=Mount $NAS_MOUNT (retries until the network is ready)
After=network-online.target
Wants=network-online.target
Before=docker.service

[Service]
Type=oneshot
TimeoutStartSec=0
ExecStart=/bin/sh -c 'until mountpoint -q $NAS_MOUNT || mount $NAS_MOUNT; do sleep 10; done'

[Install]
WantedBy=multi-user.target
UNIT
  systemctl daemon-reload
  systemctl enable makemkv-nas-mount.service
  systemctl start makemkv-nas-mount.service
  findmnt "$NAS_MOUNT" -n -o SOURCE,FSTYPE || echo "   (not mounted yet – check NAS_SOURCE and the network)"
fi

if [ -n "$LAN" ] && command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  info "Firewall: allow port $PORT from $LAN"
  ufw allow from "$LAN" to any port "$PORT" proto tcp comment "spindle (LAN)"
fi

info "Done. Continue as a regular user: git clone https://github.com/SloppyHenry/spindle && cd spindle && ./install.sh"
