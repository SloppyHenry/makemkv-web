"""Optional (Einstellung „Automatisch einsortieren, wenn eindeutig erkannt“, Standard aus).

Nach der letzten Übertragung eines Rips wird der Ordner erkannt; nur wenn alles eindeutig ist (TMDB-Treffer, Trefferwahrscheinlichkeit ≥ 95 %, Laufzeiten
passen, kein Konflikt, nichts gesperrt, Startfolge bekannt), wird ohne Rückfrage einsortiert. Alles andere bleibt liegen. Die Aktion steht im Verlauf
(Rückgängig möglich). Jeder Schritt wird in `log` festgehalten (letzte 20 Einträge, `GET /api/media/auto`).
"""
import asyncio
import time

from app import state
from app.media import analyze, conf, organize, plan as planner

THRESHOLD = 0.95
DELAY = 20                                  # Sekunden Ruhe nach der letzten Übertragung des Ordners
log: list[dict] = []
_timers: dict[str, asyncio.TimerHandle] = {}


def _note(folder: str, msg: str, done: bool = False):
    log.append({"t": time.time(), "folder": folder, "msg": msg, "done": done})
    del log[:-20]


def folder_busy(folder: str) -> bool:
    return (any(u["status"] in state.ACTIVE and u["name"].startswith(folder + "/") for u in state.uploads)
            or any(d.job for d in state.drives.values()))


def schedule(folder: str):
    """Aus dem Upload-Hook: Ordner nach einer Ruhezeit prüfen (jede weitere Übertragung schiebt den Zeitpunkt)."""
    if not conf.cfg()["auto"] or not folder:
        return
    loop = asyncio.get_running_loop()
    if folder in _timers:
        _timers[folder].cancel()
    _timers[folder] = loop.call_later(DELAY, lambda: asyncio.create_task(run(folder)))


def build_request(res: dict) -> dict | None:
    """Aus einer Erkennung eine Einsortier-Anfrage machen – oder None, wenn nicht alles eindeutig ist."""
    det, tm = res["detect"], res["tmdb"]
    ch = tm.get("chosen")
    if not ch or det["kind"] not in ("movie", "series") or det["confidence"] < THRESHOLD or tm["similarity"] < 0.85:
        return None
    req = {"kind": det["kind"], "title": ch["title"], "year": ch["year"], "tmdb": ch["tmdb"], "imdb": ch["imdb"], "poster": ch["poster"], "auto": True,
           "season": det["season"], "disc": det["disc"], "items": [], "decisions": {}}
    if det["kind"] == "movie":
        movies = [i for i in det["items"] if i["role"] == "movie"]
        if len(movies) != 1:
            return None
        req["items"] = [{"path": i["path"], "role": "movie" if i["role"] == "movie" else "skip", "why": "Extra bleibt liegen"} for i in det["items"]]
        return req
    if res["start"]["estimated"] or not res["episodes"]["assigned"] or res["episodes"]["error"]:
        return None
    if any(a["delta"] is None or abs(a["delta"]) > 6 for a in res["episodes"]["assigned"]):
        return None
    by = {a["path"]: a for a in res["episodes"]["assigned"]}
    for i in det["items"]:
        a = by.get(i["path"])
        req["items"].append({"path": i["path"], "role": "episode", "season": a["season"], "episodes": a["episodes"], "name": a["name"]} if a
                            else {"path": i["path"], "role": "skip", "why": "Play-All/Extra bleibt liegen"})
    return req


async def run(folder: str, tries: int = 0):
    _timers.pop(folder, None)
    st = conf.cfg()
    if not st["auto"] or not st["tmdb_key"]:
        return
    if folder_busy(folder):
        if tries < 90:
            _timers[folder] = asyncio.get_running_loop().call_later(DELAY, lambda: asyncio.create_task(run(folder, tries + 1)))
        return
    try:
        req = build_request(await analyze.analyze([folder]))
        if not req:
            return _note(folder, "nicht eindeutig genug, bleibt liegen")
        p = planner.build_plan(req)
        s = p["summary"]
        if not p["ok"] or s["conflict"] or s["locked"] or s["error"] or s["missing"]:
            return _note(folder, "Konflikte oder gesperrte Dateien, bleibt liegen")
        r = await organize.start(req)
        _note(folder, f"einsortiert als „{req['title']}“ ({s['move']} Dateien, Aktion {r['id']})", True)
    except Exception as e:  # noqa: BLE001
        _note(folder, f"Fehler: {e}")
