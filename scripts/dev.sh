#!/usr/bin/env bash
# Lokale Entwicklungsumgebung (macOS/Linux) – ohne Docker, ohne echtes Laufwerk, ohne NAS.
#
#   scripts/dev.sh [start] [--port 8790] [--name dev-a] [--peers "b=http://127.0.0.1:8791"] [--bg] [--reset] [--no-samples]
#   scripts/dev.sh pair      zwei Instanzen nebeneinander: dev-a (8790) und dev-b (8791), gemeinsames Ausgabeziel, kennen sich per PEERS
#   scripts/dev.sh stop      alle im Hintergrund gestarteten Instanzen beenden
#   scripts/dev.sh status    laufende Instanzen zeigen
#   scripts/dev.sh disc [--name dev-a] ready|empty|open    Disc im Attrappen-Laufwerk sr0 einlegen/entfernen/Schublade öffnen
#
# Alles liegt in $MKW_DEV_DIR (Standard: $TMPDIR/makemkv-web-dev):
#   output/            gemeinsames „NAS“ mit Beispieldateien (alle Instanzen schreiben hierher, wie im echten Verbund)
#   <name>/            data/ (config.json …), staging/ (Zwischenspeicher), drives/ (Attrappen-Laufwerke), dev.log, dev.pid
# Nichts davon berührt echte Rechner oder das NAS. makemkvcon ist eine Attrappe (scripts/dev-bin).
# Weitere Umgebungsvariablen: DEV_ASGI (Standard app.main:app), DEV_APP_DIR (Standard: Repo-Wurzel), DEV_RIP_SECONDS (Dauer eines Fake-Rips).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="${MKW_DEV_DIR:-${TMPDIR:-/tmp}/makemkv-web-dev}"
BASE="${BASE%/}"
CMD="start"; PORT=8790; NAME="dev-a"; PEERS_ARG=""; BG=0; RESET=0; SAMPLES=1; DISC_STATE=""

case "${1:-}" in start|pair|stop|status|disc) CMD="$1"; shift ;; esac
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    --peers) PEERS_ARG="$2"; shift 2 ;;
    --bg) BG=1; shift ;;
    --reset) RESET=1; shift ;;
    --no-samples) SAMPLES=0; shift ;;
    ready|empty|open) DISC_STATE="$1"; shift ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "Unbekannte Option: $1 (siehe --help)" >&2; exit 2 ;;
  esac
done

python_bin() {   # Python mit fastapi/uvicorn; sonst eigene virtuelle Umgebung unter $BASE/venv
  local py="${PYTHON:-}" c
  if [ -z "$py" ]; then   # die App braucht Python ab 3.10: erstes passende nehmen
    for c in python3 python3.13 python3.12 python3.11 python3.10; do
      if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then py="$c"; break; fi
    done
    [ -n "$py" ] || { echo "Python ab 3.10 nicht gefunden (PYTHON=… setzen)." >&2; exit 1; }
  fi
  if "$py" -c 'import fastapi, uvicorn' 2>/dev/null; then echo "$py"; return; fi
  if [ ! -x "$BASE/venv/bin/python" ]; then
    echo "Richte virtuelle Umgebung ein ($BASE/venv) …" >&2
    mkdir -p "$BASE" && "$py" -m venv "$BASE/venv" && "$BASE/venv/bin/pip" install -q fastapi "uvicorn[standard]" >&2
  fi
  echo "$BASE/venv/bin/python"
}

prepare() {   # prepare <name>: Ordner, Attrappen-Laufwerk, Beispieldateien
  local name="$1" inst="$BASE/$1"
  mkdir -p "$inst/data" "$inst/staging" "$inst/drives" "$BASE/output"
  [ -e "$inst/drives/sr0" ] || echo ready > "$inst/drives/sr0"
  if [ "$SAMPLES" = 1 ]; then
    if [ "$RESET" = 1 ]; then find "$BASE/output" -mindepth 1 -delete; rm -f "$BASE/.samples-copied"; fi
    "$REPO/scripts/dev-samples.sh" "$BASE/samples-cache" >&2
    if [ ! -e "$BASE/.samples-copied" ]; then cp -R "$BASE/samples-cache/." "$BASE/output/" && touch "$BASE/.samples-copied"; fi
  fi
}

run_instance() {   # run_instance <name> <port> <peers> <bg>
  local name="$1" port="$2" peers="$3" bg="$4" inst="$BASE/$1" py
  py="$(python_bin)"
  prepare "$name"
  if [ -f "$inst/dev.pid" ] && kill -0 "$(cat "$inst/dev.pid")" 2>/dev/null; then echo "$name läuft schon (PID $(cat "$inst/dev.pid")) → http://127.0.0.1:$port" >&2; return; fi
  export DATA_DIR="$inst/data" STAGING_DIR="$inst/staging" OUTPUT_DIR="$BASE/output" FALLBACK_DIR="$BASE/output" OUTPUT_MOUNT="$BASE/kein-mount"
  export INSTANCE_NAME="$name" PEERS="$peers" HIDE_DRIVES="" DEV_DRIVE_DIR="$inst/drives" PATH="$REPO/scripts/dev-bin:$PATH" TZ="${TZ:-Europe/Berlin}"
  cd "${DEV_APP_DIR:-$REPO}"
  if [ "$bg" = 1 ]; then
    nohup "$py" -m uvicorn "${DEV_ASGI:-app.main:app}" --host 127.0.0.1 --port "$port" > "$inst/dev.log" 2>&1 &
    echo $! > "$inst/dev.pid"
    echo "$name gestartet (PID $!) → http://127.0.0.1:$port   Protokoll: $inst/dev.log" >&2
  else
    echo "$name → http://127.0.0.1:$port   (Ordner: $inst, Ausgabe: $BASE/output)  Strg+C beendet" >&2
    exec "$py" -m uvicorn "${DEV_ASGI:-app.main:app}" --host 127.0.0.1 --port "$port"
  fi
}

case "$CMD" in
  start) run_instance "$NAME" "$PORT" "$PEERS_ARG" "$BG" ;;
  pair)
    run_instance dev-a 8790 "dev-b=http://127.0.0.1:8791" 1
    run_instance dev-b 8791 "dev-a=http://127.0.0.1:8790" 1
    echo "Beide laufen im Hintergrund; beenden mit: scripts/dev.sh stop" >&2 ;;
  stop)
    for pidf in "$BASE"/*/dev.pid; do
      [ -f "$pidf" ] || continue
      pid="$(cat "$pidf")"; kill "$pid" 2>/dev/null && echo "beendet: $(basename "$(dirname "$pidf")") (PID $pid)" || true; rm -f "$pidf"
    done ;;
  status)
    for pidf in "$BASE"/*/dev.pid; do
      [ -f "$pidf" ] || continue
      if kill -0 "$(cat "$pidf")" 2>/dev/null; then echo "läuft: $(basename "$(dirname "$pidf")") (PID $(cat "$pidf"))"; else echo "tot: $(basename "$(dirname "$pidf")")"; fi
    done ;;
  disc)
    [ -n "$DISC_STATE" ] || { echo "Zustand fehlt: ready | empty | open" >&2; exit 2; }
    mkdir -p "$BASE/$NAME/drives" && echo "$DISC_STATE" > "$BASE/$NAME/drives/sr0" && echo "$NAME: sr0 = $DISC_STATE" ;;
esac
