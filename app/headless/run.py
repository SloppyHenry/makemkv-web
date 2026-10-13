"""Flow in headless mode: after the automatic analysis choose titles (plan.py), rip and eject the disc.

- Ripping as via the interface (rip.prepare_rip/do_rip), afterwards always eject – even on errors and "by hand".
  Only a cancel by the user leaves the disc in (then someone is standing in front of it).
- If a disc that was ejected "by hand" is inserted again, it stays in the drive: choose titles in the title list and
  rip them. The memory (memory.py) remembers this selection for next time.
- The disc identifiers are read after every analysis (even without headless mode), for the memory and reports to TheDiscDB.
"""
import asyncio
import json
import time
from collections import deque
from pathlib import Path

from fastapi import HTTPException

from app import rip
from app.config import DATA
from app.drives import CDROM_EJECT, drive_status, tray
from app.headless import memory, plan as planner
from app.state import broadcast, drives, settings

HISTORY = DATA / "headless.json"
history: deque = deque(maxlen=40)
_next_id = [1]
_headless_devs: set[str] = set()                 # drives currently ripping in headless mode (not into the memory)
WAIT_SECONDS = 24 * 3600
STATE_TEXT = {"identify": "identifying", "rip": "ripping", "done": "done", "error": "error", "manual": "please by hand", "cancelled": "cancelled",
              "test": "test", "waiting": "waiting for selection"}


def cfg() -> dict:
    return settings.get("headless") or {}


# ---------------------------------------------------------------- log
def load_history():
    try:
        items = json.loads(HISTORY.read_text())
        history.extend(items[-history.maxlen:])
        _next_id[0] = max([e.get("id", 0) for e in history] + [0]) + 1
        for e in history:
            if e.get("state") in ("identify", "rip"):     # interrupted by a restart
                e.update(state="error", message="interrupted by a restart")
    except (OSError, ValueError):
        pass


def save_history():
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        HISTORY.write_text(json.dumps(list(history), ensure_ascii=False))
    except OSError as e:
        print("headless: log not saved:", e, flush=True)


def _entry(drive, state: str, key: str = "") -> dict:
    disc = drive.disc or {}
    e = {"id": _next_id[0], "t": time.time(), "drive": Path(drive.dev).name, "disc": disc.get("name") or disc.get("volume") or drive.label or "",
         "key": key, "state": state, "source": "", "mode": "", "folder": "", "titles": [], "reasons": [], "message": "", "ejected": False}
    _next_id[0] += 1
    history.append(e)
    return e


def _update(e: dict, **kw):
    e.update(kw)
    save_history()
    broadcast()


def snapshot() -> dict:
    return {"enabled": bool(cfg().get("enabled")), "memory": memory.count(),
            "history": [dict(e, state_text=STATE_TEXT.get(e["state"], e["state"])) for e in reversed(history)][:20]}


def clear_history():
    history.clear()
    save_history()
    broadcast()


# ---------------------------------------------------------------- flow
async def _eject(drive, e: dict):
    await asyncio.sleep(1)
    try:
        if await asyncio.to_thread(drive_status, drive.dev) != "open":
            await asyncio.to_thread(tray, drive.dev, CDROM_EJECT)
            drive.add_log("Headless: disc ejected.", "ok")
        _update(e, ejected=True)
    except OSError as ex:
        drive.add_log(f"Headless: eject failed: {ex}", "error")
        _update(e, message=(e["message"] + " · " if e["message"] else "") + f"Eject failed: {ex}")


def convert_cfg(disc: dict) -> dict | None:
    if not cfg().get("convert"):
        return None
    kind = "bluray" if "blu" in (disc.get("type") or "").lower() else "dvd"
    try:
        from app import convert_presets
        base = convert_presets.default_for(kind)["cfg"]
    except ImportError:
        base = (settings.get("presets") or {}).get(kind) or {}
    return {**base, "convert": True}


def _titles(p: dict) -> list[str]:
    return [p["names"].get(i) or f"Title {i + 1}" for i in p["picks"]]


async def suggest(drive) -> dict:
    """Title choice (plan.py) for the disc in the drive; ends up as the title list's preselection under disc["suggest"] in /api/state."""
    disc = drive.disc
    try:
        p = await planner.plan(drive)
    except Exception as ex:  # noqa: BLE001
        p = {"mode": "manual", "source": "", "picks": [], "names": {}, "folder": "", "reasons": [f"Detection failed: {ex}"]}
    if drive.disc is disc:                       # not analyzed again in the meantime
        disc["suggest"] = {k: p.get(k) for k in ("mode", "source", "picks", "names", "folder", "reasons")}
        broadcast()
    return p


async def on_scan(info: dict):
    drive = info["drive"]
    if drive.busy:
        return
    if not (cfg().get("enabled") and info.get("auto")):
        if drive.disc:
            await suggest(drive)
        return
    ids = await planner.get_ids(drive) if drive.disc else {}
    key = planner.ids_key(ids)
    e = _entry(drive, "identify", key)
    if not drive.disc:
        drive.add_log(f"Headless: analysis failed – {drive.error}", "error")
        _update(e, state="error", message=drive.error or "Analysis failed")
        return await _eject(drive, e)
    last = next((x for x in reversed(list(history)[:-1]) if key and x.get("key") == key), None)
    remembered, _ = await memory.lookup(ids) if last else (None, "")
    if (last and last["state"] in ("manual", "waiting") and time.time() - last["t"] < WAIT_SECONDS
            and not (remembered and remembered.get("t", 0) > last["t"])):           # ripped by hand in the meantime: the memory applies
        drive.add_log("Headless: the disc was \"by hand\" – it stays in the drive, please choose titles and rip.", "info")
        _update(e, state="waiting", message="stays in the drive: choose titles in the title list and rip – the selection is remembered")
        return await suggest(drive)
    drive.job = {"kind": "scan", "text": "Headless: determining titles …", "cur": 0, "total": 0, "started": time.time()}
    broadcast()
    try:
        p = await suggest(drive)
    finally:
        drive.job = None
    _update(e, source=p["source"], mode=p["mode"], folder=p["folder"], titles=_titles(p), reasons=p["reasons"],
            picked=[i + 1 for i in sorted(p["picks"])], skipped=planner.skips(drive.disc, p))
    for r in p["reasons"]:
        drive.add_log(f"Headless: {r}", "info")
    if p["mode"] == "manual" or not p["picks"]:
        _update(e, state="manual", message="nothing ripped – insert the disc again and choose by hand (it is remembered)")
        return await _eject(drive, e)
    req = rip.RipReq(titles=[rip.RipTitle(id=i, name=p["names"].get(i, "")) for i in p["picks"]], folder=p["folder"], mode="mkv",
                     convert=convert_cfg(drive.disc))
    try:
        dest = rip.prepare_rip(drive, req)
    except HTTPException as ex:
        drive.add_log(f"Headless: {ex.detail}", "error")
        _update(e, state="error", message=str(ex.detail))
        return await _eject(drive, e)
    _update(e, state="rip", folder=dest.name)
    _headless_devs.add(drive.dev)
    try:
        await rip.do_rip(drive, req, dest)
    finally:
        _headless_devs.discard(drive.dev)
    if drive.error == "Cancelled":
        return _update(e, state="cancelled", message="cancelled by the user – the disc stays in the drive")
    _update(e, state="error" if drive.error else "done", message=drive.error)
    await _eject(drive, e)


def on_rip(info: dict):
    """Rip hook: titles ripped by hand go into the memory (headless rips do not)."""
    if info.get("mode") != "mkv" or info["dev"] in _headless_devs:
        return
    ids = planner.cached_ids(drives.get(info["dev"]))
    if ids and planner.ids_key(ids):
        memory.record(ids, info["disc"] or {}, info["title"], Path(info["file"]).stem, info["folder"])
        broadcast()


async def probe(drive) -> dict:
    """Detect only, do not rip (button "Test detection")."""
    p = await suggest(drive)
    e = _entry(drive, "test", planner.ids_key(p.get("ids")))
    _update(e, source=p["source"], mode=p["mode"], folder=p["folder"], titles=_titles(p), reasons=p["reasons"],
            picked=[i + 1 for i in sorted(p["picks"])], skipped=planner.skips(drive.disc, p))
    return {**p, "ids": {k: v for k, v in p.get("ids", {}).items() if k != "files"}}
