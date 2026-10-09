#!/usr/bin/env bash
# Einmalige Einrichtung eines Rechners für MakeMKV Web – der Teil, der root braucht (Debian/Ubuntu):
# Docker + Compose, Kernelmodule für das Laufwerk, Ziel-Laufwerk (NFS) mit Wiederholung beim Booten,
# Firewall-Freigabe für das LAN. Mehrfaches Ausführen ist unschädlich.
#
#   sudo NAS_SOURCE=192.168.178.4:/mnt/HDD/Data LAN=192.168.178.0/24 ./scripts/setup-host.sh
#
# NAS_SOURCE  NFS-Quelle des Ausgabeziels (leer = kein NAS einhängen)
# NAS_MOUNT   Einhängepunkt (Standard /mnt/datenstein)
# LAN         Netz, das die Weboberfläche erreichen darf (leer = keine Firewall-Regel)
# PORT        Port der Weboberfläche (Standard 8780)
# Danach als normaler Benutzer: git clone … && cd makemkv-web && ./install.sh
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Bitte mit sudo ausführen."; exit 1; }
NAS_SOURCE="${NAS_SOURCE:-}"
NAS_MOUNT="${NAS_MOUNT:-/mnt/datenstein}"
LAN="${LAN:-}"
PORT="${PORT:-8780}"
WER="${SUDO_USER:-}"
info() { printf '\033[1m==>\033[0m %s\n' "$*"; }

info "Pakete: Docker, Compose$([ -n "$NAS_SOURCE" ] && echo ', nfs-common')"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y docker.io docker-compose-v2 ${NAS_SOURCE:+nfs-common}
systemctl enable --now docker
if [ -n "$WER" ] && ! id -nG "$WER" | grep -qw docker; then
  usermod -aG docker "$WER"
  echo "   $WER ist jetzt in der Gruppe docker – einmal neu anmelden (oder 'newgrp docker')."
fi

info "Kernelmodule sg + sr_mod (Zugriff auf optische Laufwerke)"
printf 'sg\nsr_mod\n' > /etc/modules-load.d/makemkv.conf
modprobe sg sr_mod 2>/dev/null || true

if [ -n "$NAS_SOURCE" ]; then
  info "Ziel einhängen: $NAS_SOURCE -> $NAS_MOUNT"
  mkdir -p "$NAS_MOUNT"
  grep -qF " $NAS_MOUNT " /etc/fstab || \
    echo "$NAS_SOURCE $NAS_MOUNT nfs4 rw,nofail,_netdev,x-systemd.mount-timeout=20 0 0" >> /etc/fstab
  # Beim Booten ist das Netz (WLAN) oft noch nicht da: wiederholen, bis es klappt – und zwar vor Docker,
  # damit der Container das Ziel einbinden kann.
  cat > /etc/systemd/system/makemkv-nas-mount.service <<UNIT
[Unit]
Description=Ziel $NAS_MOUNT einhängen (wiederholt, bis das Netzwerk bereit ist)
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
  findmnt "$NAS_MOUNT" -n -o SOURCE,FSTYPE || echo "   (noch nicht eingehängt – prüfe NAS_SOURCE und das Netzwerk)"
fi

if [ -n "$LAN" ] && command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  info "Firewall: Port $PORT für $LAN freigeben"
  ufw allow from "$LAN" to any port "$PORT" proto tcp comment "makemkv-web (LAN)"
fi

info "Fertig. Weiter als normaler Benutzer: git clone https://github.com/SloppyHenry/makemkv-web && cd makemkv-web && ./install.sh"
