"""Headless-Modus: Disc einlegen → richtige Titel werden gerippt → Disc wird ausgeworfen (fertig, nächste Disc).

Titelwahl (plan.py): Gedächtnis (memory.py) → TheDiscDB (discid.py/discdb.py) → TMDB-Laufzeiten (tmdbmatch.py) → Struktur (choose.py).
Einstellungen im Namensraum `headless` (enabled, use_db, convert), Status unter `headless` in /api/state, Protokoll in DATA/headless.json.
API: POST /api/headless/test/{laufwerk} (nur erkennen), /clear (Protokoll leeren), /memory/lookup (für andere Rechner), /memory/forget,
/contribute/{laufwerk}/prefill und /contribute/{laufwerk} (Disc an TheDiscDB melden, `send: false` = Vorschau).
"""
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import ext
from app.drives import get_drive
from app.headless import contribute, memory, run
from app.state import broadcast

router = APIRouter(prefix="/api/headless")


class HeadlessSettings(BaseModel):
    enabled: bool = False       # Headless-Modus an
    use_db: bool = True         # TheDiscDB fragen
    convert: bool = False       # nach dem Rippen mit dem Standard-Preset der Disc-Art konvertieren


class MemoryReq(BaseModel):
    disc_id: str = ""
    content_hash: str = ""


def _ready_drive(n: str, what: str):
    dr = get_drive(n)
    if dr.busy:
        raise HTTPException(409, "Laufwerk ist beschäftigt")
    if not dr.disc:
        raise HTTPException(409, "Disc wurde noch nicht analysiert")
    dr.job = {"kind": "scan", "text": what, "cur": 0, "total": 0, "started": time.time()}
    broadcast()
    return dr


def _release(dr):
    dr.job = None
    broadcast()


@router.post("/test/{n}")
async def api_test(n: str):
    dr = _ready_drive(n, "Erkennung wird getestet …")
    try:
        return await run.probe(dr)
    finally:
        _release(dr)


@router.post("/clear")
async def api_clear():
    run.clear_history()
    return {"ok": True}


@router.post("/memory/lookup")
async def api_memory_lookup(req: MemoryReq):
    return {"entry": memory.find_local(req.disc_id.upper(), req.content_hash.upper())}


@router.post("/memory/forget")
async def api_memory_forget(req: MemoryReq):
    ok = memory.forget(req.disc_id.upper(), req.content_hash.upper())
    broadcast()
    return {"ok": ok}


@router.post("/contribute/{n}/prefill")
async def api_contribute_prefill(n: str):
    dr = _ready_drive(n, "Meldung an TheDiscDB wird vorbereitet …")
    try:
        return await contribute.prefill(dr)
    finally:
        _release(dr)


@router.post("/contribute/{n}")
async def api_contribute(n: str, req: contribute.ContribReq):
    dr = get_drive(n)
    if not dr.disc:
        raise HTTPException(409, "Disc wurde noch nicht analysiert")
    ids = await run.planner.get_ids(dr) if not dr.busy else (run.planner.cached_ids(dr) or {})
    try:
        payload, log = contribute.build(dr.disc, ids, dr.scan_raw, req)
        if not req.send:
            return {"payload": payload, "log_lines": log.count("\n")}
        res = await contribute.submit(payload, log)
    except contribute.ContribError as e:
        raise HTTPException(400, str(e))
    dr.add_log(f"An TheDiscDB gemeldet ({'aktualisiert' if res['updated'] else 'neu'}); TheDiscDB prüft die Einreichung.", "ok")
    broadcast()
    return res


async def _startup():
    run.load_history()


ext.register_settings("headless", HeadlessSettings, HeadlessSettings().model_dump())
ext.register_scan_hook(run.on_scan, force_auto_scan=lambda: bool(run.cfg().get("enabled")))
ext.register_rip_hook(run.on_rip)
ext.register_snapshot("headless", run.snapshot)
ext.register_capability("headless", True)
ext.register_capability("headless_memory", True)
ext.register_router(router)
ext.register_startup(_startup)
for _p in (r"headless/test/[A-Za-z0-9]+", r"headless/clear", r"headless/memory/forget", r"headless/contribute/[A-Za-z0-9]+(/prefill)?"):
    ext.allow_proxy(_p)
