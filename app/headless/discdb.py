"""TheDiscDB (thediscdb.com): Disc nachschlagen und deren Titel den MakeMKV-Titeln zuordnen.

Abfrage ohne Anmeldung: GET /api/discid/<Disc-ID> (Liste) und /api/dischash/<Inhalts-Hash> (ein Eintrag).
Jeder Titel dort hat optional ein `item` mit `type` (MainMovie, Episode, Extra, Trailer, DeletedScene …), bei Folgen `season`/`episode`.
Zugeordnet wird über Laufzeit plus Playlist (Blu-ray, `source_file` = MakeMKV-Attribut 16) bzw. Größe (DVD); die Titelnummern
weichen ab, weil dort ohne Mindestlänge gescannt wurde. `HEADLESS_DISCDB_BASE` überschreibt die Adresse (Tests).
"""
import asyncio
import json
import os
import time
import urllib.error
import urllib.request

from app.util import hms_to_sec

BASE = os.environ.get("HEADLESS_DISCDB_BASE", "https://thediscdb.com").rstrip("/")
TTL_HIT, TTL_MISS = 30 * 86400, 86400
_cache: dict[str, tuple[float, dict | None]] = {}


class DiscDbError(Exception):
    pass


def _http_get(url: str, timeout: float = 15) -> tuple[int, bytes]:
    """Einzige Stelle mit Netzwerkzugriff (Tests ersetzen sie)."""
    req = urllib.request.Request(url, headers={"User-Agent": "spindle", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        with e:
            return e.code, e.read()


async def _get(path: str) -> dict | list | None:
    hit = _cache.get(path)
    if hit and hit[0] > time.time():
        return hit[1]
    try:
        status, body = await asyncio.to_thread(_http_get, BASE + path)
    except OSError as e:
        raise DiscDbError(f"TheDiscDB nicht erreichbar: {e}") from e
    if status == 404:
        _cache[path] = (time.time() + TTL_MISS, None)
        return None
    if status != 200:
        raise DiscDbError(f"TheDiscDB antwortet mit {status}")
    try:
        val = json.loads(body)
    except ValueError as e:
        raise DiscDbError("TheDiscDB: unlesbare Antwort") from e
    _cache[path] = (time.time() + TTL_HIT, val)
    return val


async def lookup(disc_id: str, content_hash: str) -> tuple[dict | None, str]:
    """Erst über die Disc-ID, dann über den Inhalts-Hash. Rückgabe (Eintrag oder None, womit gefunden)."""
    if disc_id:
        v = await _get(f"/api/discid/{disc_id}")
        if isinstance(v, list) and v:
            return v[0], "Disc-ID"
        if isinstance(v, dict) and v.get("titles") is not None:
            return v, "Disc-ID"
    if content_hash:
        v = await _get(f"/api/dischash/{content_hash}")
        if isinstance(v, dict) and v.get("titles") is not None:
            return v, "Inhalts-Hash"
    return None, ""


def _same_size(a: int, b: int) -> bool:
    return bool(a and b) and abs(a - b) <= max(4096, int(5e-5 * max(a, b)))


def candidates(dt: dict, titles: list[dict], bluray: bool) -> list[int]:
    dur = hms_to_sec(dt.get("duration") or "")
    src = (dt.get("source_file") or "").lower()
    out = []
    for t in titles:
        if abs(t["duration"] - dur) > 2:
            continue
        tsrc = (t.get("source") or "").lower()
        if bluray and src.endswith((".mpls", ".m2ts")) and tsrc:
            if tsrc != src:
                continue
        elif not _same_size(int(dt.get("size") or 0), t["bytes"]):
            continue
        seg = (dt.get("segment_map") or "").replace(" ", "")
        if seg and t.get("segments") and t["segments"].replace(" ", "") != seg and not bluray:
            continue
        out.append(t["id"])
    return out


def match(entry: dict, disc: dict) -> dict:
    """Gewünschte Titel (Hauptfilm bzw. Folgen) den gescannten Titeln zuordnen.
    Ergebnis: {ok, kind: movie|series, title, year, disc_name, picks: [{id, type, season, episode, item}], reason}."""
    media = entry.get("media") or {}
    kind = "series" if (media.get("type") or "").lower() == "series" else "movie"
    want_type = "episode" if kind == "series" else "mainmovie"
    bluray = "blu" in (entry.get("format") or disc.get("type") or "").lower()
    res = {"ok": False, "kind": kind, "title": media.get("title") or "", "year": media.get("year") or None,
           "disc_name": (entry.get("disc") or {}).get("name") or "", "picks": [], "reason": "",
           "tmdb": (media.get("external_ids") or {}).get("tmdb") or ""}
    wanted = [dt for dt in entry.get("titles") or [] if ((dt.get("item") or {}).get("type") or "").lower() == want_type]
    if not wanted:
        res["reason"] = "Eintrag ohne " + ("Folgen" if kind == "series" else "Hauptfilm")
        return res
    used: set[int] = set()
    for dt in wanted:
        c = [i for i in candidates(dt, disc["titles"], bluray) if i not in used]
        if len(c) != 1:
            res["reason"] = (f"Titel {dt.get('source_file') or dt.get('index')} ({dt.get('duration')}) "
                             + ("nicht gefunden" if not c else "nicht eindeutig") + " – Disc weicht vom Eintrag ab")
            res["picks"] = []
            return res
        used.add(c[0])
        it = dt.get("item") or {}
        res["picks"].append({"id": c[0], "type": it.get("type"), "season": it.get("season"), "episode": it.get("episode"),
                             "item": it.get("title") or ""})
    res["ok"] = True
    return res
