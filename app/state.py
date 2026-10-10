"""Laufzeitstatus, Benachrichtigung der Browser und die Statusmeldung (/api/state, /api/events)."""
import asyncio
import copy
import json
import os
import shutil
import time

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app import ext
from app.config import DEFAULTS, INSTANCE, OUT_FALLBACK, OUT_PREFERRED, STAGING

router = APIRouter()

settings = copy.deepcopy(DEFAULTS)
drives: dict = {}                        # Gerätepfad -> app.drives.Drive
hidden_drives: set[str] = set()
clients: set[asyncio.Queue] = set()
beta = {"key": "", "fetched": 0, "error": ""}
out_cache = {"dir": str(OUT_FALLBACK), "mounted": False, "free": 0, "stalled": False}

uploads: list[dict] = []
upload_queue: asyncio.Queue = asyncio.Queue()
ACTIVE = ("queued", "copying", "retry")

conversions: list[dict] = []
convert_queue: asyncio.Queue = asyncio.Queue()
conv_procs: dict[int, list] = {}
conv_state = {"paused": False}      # Konvertierung angehalten (ffmpeg per SIGSTOP, Warteschlange wartet)
CV_ACTIVE = ("queued", "running")

peers_state: dict[str, dict] = {}


def broadcast():
    for q in list(clients):
        if q.empty():
            q.put_nowait(1)


def capacity() -> dict:
    try:
        load = os.getloadavg()[0]
    except OSError:
        load = 0.0
    return {"instance": INSTANCE, "cores": os.cpu_count() or 1, "load": round(load, 2),
            "conv_active": sum(1 for c in conversions if c["status"] in CV_ACTIVE), "conv_paused": conv_state["paused"]}


def work_pending() -> bool:
    """Läuft hier noch Arbeit (Rip, Konvertierung, Übertragung)? Wenn nicht, darf der Rechner heruntergefahren werden."""
    return (any(d.job for d in drives.values()) or any(c["status"] in CV_ACTIVE for c in conversions)
            or any(u["status"] in ACTIVE for u in uploads))


def public_settings() -> dict:
    """Einstellungen für Browser und andere Rechner: geheime Felder der Erweiterungs-Namensräume sind ausgeblendet."""
    out = dict(settings)
    for ns, spec in ext.settings_ns.items():
        if isinstance(out.get(ns), dict) and spec["secret"]:
            out[ns] = {k: v for k, v in out[ns].items() if k not in spec["secret"]}
            out[ns].update({f"{k}_set": bool(settings[ns].get(k)) for k in spec["secret"]})
    return out


def snapshot():
    snap = {
        "drives": [dr.public() for dr in sorted(drives.values(), key=lambda x: (0 if (x.job or x.disc) else 1 if x.status == "ready" else 2, x.dev))],
        "settings": public_settings(),
        "output": {"dir": out_cache["dir"], "mounted": out_cache["mounted"], "preferred": str(OUT_PREFERRED),
                   "free": out_cache["free"], "stalled": out_cache["stalled"]},
        "uploads": [{k: u[k] for k in ("id", "name", "size", "copied", "status", "error", "t", "speed", "eta", "replace")} for u in uploads
                    if not (u["status"] == "done" and time.time() - u["t"] > 600)],
        "conversions": [{k: c.get(k) for k in ("id", "name", "size_in", "size_out", "status", "pct", "fps", "speed", "eta", "error", "cfg", "t", "started", "mode", "origin", "paused", "handed", "cancel")}
                        for c in conversions if not (c["status"] in ("done", "skipped") and time.time() - c["t"] > 900)],
        "conv_paused": conv_state["paused"],
        "capacity": capacity(),
        "peers": sorted(peers_state.values(), key=lambda x: x["name"]),
        "idle": not work_pending(),
        "staging": {"dir": str(STAGING), "free": shutil.disk_usage(STAGING).free if STAGING.exists() else 0},
        "key": {"custom": bool(settings["key"].strip()), "beta": bool(beta["key"]), "fetched": beta["fetched"], "error": beta["error"]},
        "capabilities": ext.capabilities,
        "now": time.time(),
    }
    for key, fn in ext.snapshot_fns.items():          # Erweiterungen: ein Fehler darf die Statusmeldung nicht zerstören
        try:
            snap[key] = fn()
        except Exception as e:  # noqa: BLE001
            print(f"snapshot[{key}]: {e}", flush=True)
    return snap


@router.get("/api/state")
def api_state():
    return snapshot()


@router.get("/api/events")
async def api_events():
    q: asyncio.Queue = asyncio.Queue(maxsize=1)
    clients.add(q)

    async def gen():
        try:
            yield f"data: {json.dumps(await asyncio.to_thread(snapshot))}\n\n"
            while True:
                try:
                    await asyncio.wait_for(q.get(), timeout=10)
                except asyncio.TimeoutError:
                    pass
                await asyncio.sleep(0.15)
                yield f"data: {json.dumps(await asyncio.to_thread(snapshot))}\n\n"
        finally:
            clients.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
