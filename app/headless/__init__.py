"""Headless-Modus: Disc einlegen → richtige Titel werden gerippt → Disc wird ausgeworfen (fertig, nächste Disc).

Titelwahl über TheDiscDB (Disc-ID bzw. Inhalts-Hash, siehe discid.py/discdb.py), sonst über die Struktur der Disc (choose.py).
Einstellungen im Namensraum `headless` (enabled, use_db, convert), Status unter `headless` in /api/state, Protokoll in DATA/headless.json.
API: POST /api/headless/test/{laufwerk} (nur erkennen, nichts rippen), POST /api/headless/clear (Protokoll leeren).
"""
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import ext
from app.drives import get_drive
from app.headless import run
from app.state import broadcast

router = APIRouter(prefix="/api/headless")


class HeadlessSettings(BaseModel):
    enabled: bool = False       # Headless-Modus an
    use_db: bool = True         # TheDiscDB fragen
    convert: bool = False       # nach dem Rippen mit dem Standard-Preset der Disc-Art konvertieren


@router.post("/test/{n}")
async def api_test(n: str):
    dr = get_drive(n)
    if dr.busy:
        raise HTTPException(409, "Laufwerk ist beschäftigt")
    if not dr.disc:
        raise HTTPException(409, "Disc wurde noch nicht analysiert")
    dr.job = {"kind": "scan", "text": "Erkennung wird getestet …", "cur": 0, "total": 0, "started": time.time()}
    broadcast()
    try:
        return await run.probe(dr)
    finally:
        dr.job = None
        broadcast()


@router.post("/clear")
async def api_clear():
    run.clear_history()
    return {"ok": True}


async def _startup():
    run.load_history()


ext.register_settings("headless", HeadlessSettings, HeadlessSettings().model_dump())
ext.register_scan_hook(run.on_scan, force_auto_scan=lambda: bool(run.cfg().get("enabled")))
ext.register_snapshot("headless", run.snapshot)
ext.register_capability("headless", True)
ext.register_router(router)
ext.register_startup(_startup)
ext.allow_proxy(r"headless/test/[A-Za-z0-9]+")
ext.allow_proxy(r"headless/clear")
