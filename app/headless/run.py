"""Ablauf im Headless-Modus: nach der automatischen Analyse Titel wählen (plan.py), rippen und die Disc auswerfen.

- Rippen wie über die Oberfläche (rip.prepare_rip/do_rip), danach immer auswerfen – auch bei Fehlern und „von Hand“.
  Nur ein Abbruch durch den Nutzer lässt die Disc drin (dann steht jemand davor).
- Wird eine Disc, die „von Hand“ ausgeworfen wurde, wieder eingelegt, bleibt sie im Laufwerk: Titel in der Titelliste wählen und
  rippen. Diese Auswahl merkt sich das Gedächtnis (memory.py) für das nächste Mal.
- Die Disc-Kennungen werden nach jeder Analyse gelesen (auch ohne Headless-Modus), für Gedächtnis und Meldung an TheDiscDB.
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
_headless_devs: set[str] = set()                 # Laufwerke, die gerade im Headless-Modus rippen (nicht ins Gedächtnis)
WAIT_SECONDS = 24 * 3600
STATE_TEXT = {"identify": "erkennt", "rip": "rippt", "done": "fertig", "error": "Fehler", "manual": "bitte von Hand", "cancelled": "abgebrochen",
              "test": "Probe", "waiting": "wartet auf Auswahl"}


def cfg() -> dict:
    return settings.get("headless") or {}


# ---------------------------------------------------------------- Protokoll
def load_history():
    try:
        items = json.loads(HISTORY.read_text())
        history.extend(items[-history.maxlen:])
        _next_id[0] = max([e.get("id", 0) for e in history] + [0]) + 1
        for e in history:
            if e.get("state") in ("identify", "rip"):     # beim Neustart unterbrochen
                e.update(state="error", message="durch Neustart unterbrochen")
    except (OSError, ValueError):
        pass


def save_history():
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        HISTORY.write_text(json.dumps(list(history), ensure_ascii=False))
    except OSError as e:
        print("headless: Protokoll nicht gespeichert:", e, flush=True)


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


# ---------------------------------------------------------------- Ablauf
async def _eject(drive, e: dict):
    await asyncio.sleep(1)
    try:
        if await asyncio.to_thread(drive_status, drive.dev) != "open":
            await asyncio.to_thread(tray, drive.dev, CDROM_EJECT)
            drive.add_log("Headless: Disc ausgeworfen.", "ok")
        _update(e, ejected=True)
    except OSError as ex:
        drive.add_log(f"Headless: Auswerfen fehlgeschlagen: {ex}", "error")
        _update(e, message=(e["message"] + " · " if e["message"] else "") + f"Auswerfen fehlgeschlagen: {ex}")


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
    return [p["names"].get(i) or f"Titel {i + 1}" for i in p["picks"]]


async def on_scan(info: dict):
    drive = info["drive"]
    ids = await planner.get_ids(drive) if drive.disc and not drive.busy else {}
    if not (cfg().get("enabled") and info.get("auto")) or drive.busy:
        return
    key = planner.ids_key(ids)
    e = _entry(drive, "identify", key)
    if not drive.disc:
        drive.add_log(f"Headless: Analyse fehlgeschlagen – {drive.error}", "error")
        _update(e, state="error", message=drive.error or "Analyse fehlgeschlagen")
        return await _eject(drive, e)
    last = next((x for x in reversed(list(history)[:-1]) if key and x.get("key") == key), None)
    remembered, _ = await memory.lookup(ids) if last else (None, "")
    if (last and last["state"] in ("manual", "waiting") and time.time() - last["t"] < WAIT_SECONDS
            and not (remembered and remembered.get("t", 0) > last["t"])):           # inzwischen von Hand gerippt: Gedächtnis gilt
        drive.add_log("Headless: Disc war „von Hand“ – bleibt im Laufwerk, bitte Titel wählen und rippen.", "info")
        return _update(e, state="waiting", message="bleibt im Laufwerk: Titel in der Titelliste wählen und rippen – die Auswahl wird gemerkt")
    drive.job = {"kind": "scan", "text": "Headless: Titel werden bestimmt …", "cur": 0, "total": 0, "started": time.time()}
    broadcast()
    try:
        p = await planner.plan(drive)
    except Exception as ex:  # noqa: BLE001
        p = {"mode": "manual", "source": "", "picks": [], "names": {}, "folder": "", "reasons": [f"Erkennung fehlgeschlagen: {ex}"]}
    finally:
        drive.job = None
    _update(e, source=p["source"], mode=p["mode"], folder=p["folder"], titles=_titles(p), reasons=p["reasons"])
    for r in p["reasons"]:
        drive.add_log(f"Headless: {r}", "info")
    if p["mode"] == "manual" or not p["picks"]:
        _update(e, state="manual", message="nichts gerippt – Disc wieder einlegen und von Hand wählen (wird gemerkt)")
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
    if drive.error == "Abgebrochen":
        return _update(e, state="cancelled", message="vom Nutzer abgebrochen – Disc bleibt im Laufwerk")
    _update(e, state="error" if drive.error else "done", message=drive.error)
    await _eject(drive, e)


def on_rip(info: dict):
    """Rip-Hook: von Hand gerippte Titel ins Gedächtnis (Headless-Rips nicht)."""
    if info.get("mode") != "mkv" or info["dev"] in _headless_devs:
        return
    ids = planner.cached_ids(drives.get(info["dev"]))
    if ids and planner.ids_key(ids):
        memory.record(ids, info["disc"] or {}, info["title"], Path(info["file"]).stem, info["folder"])
        broadcast()


async def probe(drive) -> dict:
    """Nur erkennen, nicht rippen (Knopf „Erkennung testen“)."""
    p = await planner.plan(drive)
    e = _entry(drive, "test", planner.ids_key(p.get("ids")))
    _update(e, source=p["source"], mode=p["mode"], folder=p["folder"], titles=_titles(p), reasons=p["reasons"])
    return {**p, "ids": {k: v for k, v in p.get("ids", {}).items() if k != "files"}}
