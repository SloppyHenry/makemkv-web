"""Ablauf im Headless-Modus: nach der automatischen Analyse Titel wählen, rippen und die Disc auswerfen.

1. Disc-Kennungen lesen und in TheDiscDB nachschlagen. Treffer: genau der Hauptfilm bzw. die Folgen (mit Namen S01E02 …).
2. Kein Treffer: Struktur der Disc (choose.decide), TMDB nur als Gegenprobe des Namens.
3. Rippen wie über die Oberfläche (rip.prepare_rip/do_rip), danach immer auswerfen – auch bei Fehlern und „von Hand“.
   Nur ein Abbruch durch den Nutzer lässt die Disc drin (dann steht jemand davor).
"""
import asyncio
import json
import re
import time
from collections import deque
from pathlib import Path

from fastapi import HTTPException

from app import rip
from app.config import DATA, DEV_DRIVE_DIR
from app.drives import CDROM_EJECT, drive_status, tray
from app.headless import choose, discdb, discid, udf
from app.media import detect
from app.state import broadcast, settings

HISTORY = DATA / "headless.json"
history: deque = deque(maxlen=40)
_next_id = [1]
STATE_TEXT = {"identify": "erkennt", "rip": "rippt", "done": "fertig", "error": "Fehler", "manual": "bitte von Hand", "cancelled": "abgebrochen",
              "test": "Probe"}


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


def _entry(drive, state: str) -> dict:
    disc = drive.disc or {}
    e = {"id": _next_id[0], "t": time.time(), "drive": Path(drive.dev).name, "disc": disc.get("name") or disc.get("volume") or drive.label or "",
         "state": state, "source": "", "mode": "", "folder": "", "titles": [], "reasons": [], "message": "", "ejected": False}
    _next_id[0] += 1
    history.append(e)
    return e


def _update(e: dict, **kw):
    e.update(kw)
    save_history()
    broadcast()


def snapshot() -> dict:
    return {"enabled": bool(cfg().get("enabled")), "history": [dict(e, state_text=STATE_TEXT.get(e["state"], e["state"])) for e in reversed(history)][:20]}


def clear_history():
    history.clear()
    save_history()
    broadcast()


# ---------------------------------------------------------------- Erkennung
def read_ids(dev: str) -> dict:
    """Disc-Kennungen vom Gerät lesen (Entwicklung: Abbild <Laufwerk>.iso neben der Attrappe)."""
    path = f"{dev}.iso" if DEV_DRIVE_DIR else dev
    if DEV_DRIVE_DIR and not Path(path).exists():
        return {"error": "kein Abbild der Attrappe (Entwicklung)"}
    fs, close = udf.open_device(path)
    try:
        return discid.identify(fs)
    finally:
        close()


def _norm(s: str) -> str:
    return re.sub(r"[^0-9a-zäöüß]+", "", (s or "").casefold())


async def tmdb_hint(disc: dict) -> str:
    """„movie“/„series“, wenn TMDB den Namen der Disc genau in nur einer Art kennt; sonst leer (kein Schlüssel, kein Treffer, beides)."""
    try:
        from app.media import conf, metadata
    except ImportError:
        return ""
    st = conf.cfg()
    if not st.get("tmdb_key"):
        return ""
    a = detect.analyze_name(disc.get("name") or disc.get("volume") or "")
    if len(a["title"]) < 2:
        return ""
    found = {}
    for kind in ("movie", "tv"):
        try:
            hits = await metadata.search(st["tmdb_key"], kind, a["title"], a["year"], st.get("language") or "de-DE")
        except Exception:  # noqa: BLE001  (Netz, Schlüssel …: dann eben ohne Gegenprobe)
            return ""
        found[kind] = any(_norm(h["title"]) == _norm(a["title"]) or _norm(h["original"]) == _norm(a["title"]) for h in hits[:3])
    if found["movie"] != found["tv"]:
        return "movie" if found["movie"] else "series"
    return ""


def _clean(s: str) -> str:
    return re.sub(r"\s*:\s*", " - ", (s or "").strip())


def _ep(v) -> str:
    v = str(v or "").strip()
    return f"{int(v):02d}" if v.isdigit() else v


def names_from_db(m: dict) -> tuple[str, dict[int, str]]:
    title = _clean(m["title"]) or "Disc"
    base = f"{title} ({m['year']})" if m.get("year") else title
    names = {}
    if m["kind"] == "series":
        folder = base + (f" - {_clean(m['disc_name'])}" if m.get("disc_name") else "")
        for p in m["picks"]:
            n = f"{title} S{_ep(p['season'])}E{_ep(p['episode'])}" if p.get("episode") else title
            names[p["id"]] = n + (f" - {_clean(p['item'])}" if p.get("item") and _norm(p["item"]) != _norm(title) else "")
        return folder, names
    for k, p in enumerate(m["picks"]):
        extra = _clean(p["item"]) if p.get("item") and _norm(p["item"]) != _norm(m["title"]) else (f"Fassung {k + 1}" if len(m["picks"]) > 1 else "")
        names[p["id"]] = base + (f" - {extra}" if extra else "")
    return base, names


def names_from_disc(disc: dict, ids: list[int]) -> dict[int, str]:
    """Wie die Oberfläche (titles.js suggestName): bei gleichen Namen die Titelnummer anhängen."""
    out = {}
    for t in disc["titles"]:
        if t["id"] in ids:
            b = (t.get("name") or "").strip() or f"Titel {t['id'] + 1}"
            dup = sum(1 for x in disc["titles"] if (x.get("name") or "").strip() == b) > 1
            out[t["id"]] = f"{b} - Titel {t['id'] + 1:02d}" if dup else b
    return out


async def plan(drive) -> dict:
    """Titelwahl für die Disc im Laufwerk. {mode, source, picks, names, folder, reasons, ids}."""
    disc, reasons = drive.disc, []
    try:
        ids = await asyncio.wait_for(asyncio.to_thread(read_ids, drive.dev), 120)
    except (OSError, udf.UdfError, asyncio.TimeoutError) as e:
        ids = {"error": str(e) or "Zeitüberschreitung"}
    if ids.get("error"):
        reasons.append(f"Disc-Kennung: {ids['error']}")
    if cfg().get("use_db", True) and (ids.get("disc_id") or ids.get("content_hash")):
        try:
            entry, via = await discdb.lookup(ids.get("disc_id", ""), ids.get("content_hash", ""))
        except discdb.DiscDbError as e:
            entry, via = None, ""
            reasons.append(str(e))
        if entry:
            m = discdb.match(entry, disc)
            if m["ok"]:
                folder, names = names_from_db(m)
                what = "Folgen" if m["kind"] == "series" else "Hauptfilm"
                return {"mode": m["kind"], "source": f"TheDiscDB ({via})", "picks": [p["id"] for p in m["picks"]], "names": names, "folder": folder,
                        "reasons": [f"TheDiscDB: „{m['title']}“ ({m.get('year') or '?'}), {len(m['picks'])} × {what}"] + reasons, "ids": ids}
            reasons.append(f"TheDiscDB: {m['reason']}")
        elif via == "" and not any(r.startswith("TheDiscDB") for r in reasons):
            reasons.append("Disc nicht in TheDiscDB")
    hint = await tmdb_hint(disc)
    d = choose.decide(disc, ids.get("content_bytes") or 0, hint)
    return {"mode": d["mode"], "source": "Struktur der Disc", "picks": d["picks"], "names": names_from_disc(disc, d["picks"]),
            "folder": disc.get("name") or disc.get("volume") or "", "reasons": d["reasons"] + reasons, "ids": ids}


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


async def on_scan(info: dict):
    drive = info["drive"]
    if not (cfg().get("enabled") and info.get("auto")) or drive.busy:
        return
    e = _entry(drive, "identify")
    if not drive.disc:
        drive.add_log(f"Headless: Analyse fehlgeschlagen – {drive.error}", "error")
        _update(e, state="error", message=drive.error or "Analyse fehlgeschlagen")
        return await _eject(drive, e)
    drive.job = {"kind": "scan", "text": "Headless: Titel werden bestimmt …", "cur": 0, "total": 0, "started": time.time()}
    broadcast()
    try:
        p = await plan(drive)
    except Exception as ex:  # noqa: BLE001
        p = {"mode": "manual", "source": "", "picks": [], "names": {}, "folder": "", "reasons": [f"Erkennung fehlgeschlagen: {ex}"]}
    finally:
        drive.job = None
    titles = [p["names"].get(i) or f"Titel {i + 1}" for i in p["picks"]]
    _update(e, source=p["source"], mode=p["mode"], folder=p["folder"], titles=titles, reasons=p["reasons"])
    for r in p["reasons"]:
        drive.add_log(f"Headless: {r}", "info")
    if p["mode"] == "manual" or not p["picks"]:
        _update(e, state="manual", message="nichts gerippt – bitte von Hand wählen")
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
    await rip.do_rip(drive, req, dest)
    if drive.error == "Abgebrochen":
        return _update(e, state="cancelled", message="vom Nutzer abgebrochen – Disc bleibt im Laufwerk")
    _update(e, state="error" if drive.error else "done", message=drive.error)
    await _eject(drive, e)


async def probe(drive) -> dict:
    """Nur erkennen, nicht rippen (Knopf „Erkennung testen“)."""
    e = _entry(drive, "test")
    p = await plan(drive)
    _update(e, source=p["source"], mode=p["mode"], folder=p["folder"], titles=[p["names"].get(i) or f"Titel {i + 1}" for i in p["picks"]],
            reasons=p["reasons"])
    return {**p, "ids": {k: v for k, v in p.get("ids", {}).items() if k != "files"}}
