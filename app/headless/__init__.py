"""Headless mode: insert a disc → the right titles are ripped → the disc is ejected (done, next disc).

Title choice (plan.py): memory (memory.py) → TheDiscDB (discid.py/discdb.py) → TMDB runtimes (tmdbmatch.py) → structure (choose.py).
Settings in the `headless` namespace (enabled, use_db, convert), state under `headless` in /api/state, log in DATA/headless.json.
API: POST /api/headless/test/{drive} (detect only), /clear (clear the log), /memory/lookup (for other machines), /memory/forget,
/contribute/{drive}/prefill and /contribute/{drive} (report the disc to TheDiscDB, `send: false` = preview).
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
    enabled: bool = False       # headless mode on
    use_db: bool = True         # ask TheDiscDB
    convert: bool = False       # after ripping, convert with the default preset for the disc type


class MemoryReq(BaseModel):
    disc_id: str = ""
    content_hash: str = ""


def _ready_drive(n: str, what: str):
    dr = get_drive(n)
    if dr.busy:
        raise HTTPException(409, "Drive is busy")
    if not dr.disc:
        raise HTTPException(409, "Disc has not been analyzed yet")
    dr.job = {"kind": "scan", "text": what, "cur": 0, "total": 0, "started": time.time()}
    broadcast()
    return dr


def _release(dr):
    dr.job = None
    broadcast()


@router.post("/test/{n}")
async def api_test(n: str):
    dr = _ready_drive(n, "Testing detection …")
    try:
        return await run.probe(dr)
    finally:
        _release(dr)


class EnableReq(BaseModel):
    enabled: bool


@router.post("/enable")
async def api_enable(req: EnableReq):
    """Switch on the interface (also from other machines for their drive here)."""
    from app import settings as st
    await st.api_settings({"headless": {"enabled": req.enabled}})
    return {"ok": True, "enabled": req.enabled}


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
    dr = _ready_drive(n, "Preparing the report to TheDiscDB …")
    try:
        return await contribute.prefill(dr)
    finally:
        _release(dr)


@router.post("/contribute/{n}")
async def api_contribute(n: str, req: contribute.ContribReq):
    dr = get_drive(n)
    if not dr.disc:
        raise HTTPException(409, "Disc has not been analyzed yet")
    ids = await run.planner.get_ids(dr) if not dr.busy else (run.planner.cached_ids(dr) or {})
    try:
        payload, log = contribute.build(dr.disc, ids, dr.scan_raw, req)
        if not req.send:
            return {"payload": payload, "log_lines": log.count("\n")}
        res = await contribute.submit(payload, log)
    except contribute.ContribError as e:
        raise HTTPException(400, str(e))
    dr.add_log(f"Reported to TheDiscDB ({'updated' if res['updated'] else 'new'}); TheDiscDB reviews the submission.", "ok")
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
for _p in (r"headless/enable", r"headless/test/[A-Za-z0-9]+", r"headless/clear", r"headless/memory/forget", r"headless/contribute/[A-Za-z0-9]+(/prefill)?"):
    ext.allow_proxy(_p)
