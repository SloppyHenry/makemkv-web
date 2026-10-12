#!/usr/bin/env bash
# Local development environment (macOS/Linux) – no Docker, no real drive, no NAS.
#
#   scripts/dev.sh [start] [--port 8790] [--name dev-a] [--peers "b=http://127.0.0.1:8791"] [--bg] [--reset] [--no-samples]
#   scripts/dev.sh pair      two instances side by side: dev-a (8790) and dev-b (8791), shared output target, know each other via PEERS
#   scripts/dev.sh stop      stop all instances started in the background
#   scripts/dev.sh status    show running instances
#   scripts/dev.sh disc [--name dev-a] ready|empty|open    insert/remove a disc in the fake drive sr0 / open the tray
#
# Everything lives in $MKW_DEV_DIR (default: $TMPDIR/spindle-dev):
#   output/            shared "NAS" with sample files (all instances write here, like in a real cluster)
#   <name>/            data/ (config.json …), staging/ (buffer), drives/ (fake drives), dev.log, dev.pid
# None of this touches real machines or the NAS. makemkvcon is a stub (scripts/dev-bin).
# More environment variables: DEV_ASGI (default app.main:app), DEV_APP_DIR (default: repo root), DEV_RIP_SECONDS (duration of a fake rip).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="${MKW_DEV_DIR:-${TMPDIR:-/tmp}/spindle-dev}"
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
    *) echo "Unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac
done

python_bin() {   # Python with fastapi/uvicorn; otherwise a private virtual environment under $BASE/venv
  local py="${PYTHON:-}" c
  if [ -z "$py" ]; then   # the app needs Python 3.10 or newer: take the first match
    for c in python3 python3.13 python3.12 python3.11 python3.10; do
      if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then py="$c"; break; fi
    done
    [ -n "$py" ] || { echo "Python 3.10 or newer not found (set PYTHON=…)." >&2; exit 1; }
  fi
  if "$py" -c 'import fastapi, uvicorn' 2>/dev/null; then echo "$py"; return; fi
  if [ ! -x "$BASE/venv/bin/python" ]; then
    echo "Setting up virtual environment ($BASE/venv) …" >&2
    mkdir -p "$BASE" && "$py" -m venv "$BASE/venv" && "$BASE/venv/bin/pip" install -q fastapi "uvicorn[standard]" >&2
  fi
  echo "$BASE/venv/bin/python"
}

prepare() {   # prepare <name>: folders, fake drive, sample files
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
  if [ -f "$inst/dev.pid" ] && kill -0 "$(cat "$inst/dev.pid")" 2>/dev/null; then echo "$name is already running (PID $(cat "$inst/dev.pid")) → http://127.0.0.1:$port" >&2; return; fi
  export DATA_DIR="$inst/data" STAGING_DIR="$inst/staging" OUTPUT_DIR="$BASE/output" FALLBACK_DIR="$BASE/output" OUTPUT_MOUNT="$BASE/no-mount"
  export INSTANCE_NAME="$name" PEERS="$peers" HIDE_DRIVES="" DEV_DRIVE_DIR="$inst/drives" PATH="$REPO/scripts/dev-bin:$PATH" TZ="${TZ:-Europe/Berlin}"
  cd "${DEV_APP_DIR:-$REPO}"
  if [ "$bg" = 1 ]; then
    nohup "$py" -m uvicorn "${DEV_ASGI:-app.main:app}" --host 127.0.0.1 --port "$port" > "$inst/dev.log" 2>&1 &
    echo $! > "$inst/dev.pid"
    echo "$name started (PID $!) → http://127.0.0.1:$port   Log: $inst/dev.log" >&2
  else
    echo "$name → http://127.0.0.1:$port   (folder: $inst, output: $BASE/output)  Ctrl+C stops" >&2
    exec "$py" -m uvicorn "${DEV_ASGI:-app.main:app}" --host 127.0.0.1 --port "$port"
  fi
}

case "$CMD" in
  start) run_instance "$NAME" "$PORT" "$PEERS_ARG" "$BG" ;;
  pair)
    run_instance dev-a 8790 "dev-b=http://127.0.0.1:8791" 1
    run_instance dev-b 8791 "dev-a=http://127.0.0.1:8790" 1
    echo "Both run in the background; stop with: scripts/dev.sh stop" >&2 ;;
  stop)
    for pidf in "$BASE"/*/dev.pid; do
      [ -f "$pidf" ] || continue
      pid="$(cat "$pidf")"; kill "$pid" 2>/dev/null && echo "stopped: $(basename "$(dirname "$pidf")") (PID $pid)" || true; rm -f "$pidf"
    done ;;
  status)
    for pidf in "$BASE"/*/dev.pid; do
      [ -f "$pidf" ] || continue
      if kill -0 "$(cat "$pidf")" 2>/dev/null; then echo "running: $(basename "$(dirname "$pidf")") (PID $(cat "$pidf"))"; else echo "dead: $(basename "$(dirname "$pidf")")"; fi
    done ;;
  disc)
    [ -n "$DISC_STATE" ] || { echo "State missing: ready | empty | open" >&2; exit 2; }
    mkdir -p "$BASE/$NAME/drives" && echo "$DISC_STATE" > "$BASE/$NAME/drives/sr0" && echo "$NAME: sr0 = $DISC_STATE" ;;
esac
