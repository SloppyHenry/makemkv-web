"""Disc an TheDiscDB melden (nur auf Knopfdruck, mit Vorschau): über die offene Einreichung „Engram“ (POST /api/engram/disc,
danach das MakeMKV-Scanprotokoll an /api/engram/disc/<Inhalts-Hash>/logs/scan). TheDiscDB prüft Einreichungen von Hand, bevor sie
erscheinen. Gesendet werden Inhalts-Hash, Volume-Label, die Titel der Disc (Laufzeit, Größe, Segmente, Spuren) und die Zuordnung;
keine Dateien, keine Laufwerks-, Rechner- oder Nutzerdaten (das Protokoll enthält nur CINFO/TINFO/SINFO/TCOUNT-Zeilen).
"""
import asyncio
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

from pydantic import BaseModel

from app.config import VERSION
from app.headless import discdb, memory, plan as planner, tmdbmatch

TYPES = ("MainMovie", "Episode", "Extra", "Trailer", "DeletedScene")
_SE = re.compile(r"\bS(\d{1,2})E(\d{1,3})\b", re.I)


class ContribTitle(BaseModel):
    id: int
    type: str = "Extra"
    season: str = ""
    episode: str = ""


class ContribReq(BaseModel):
    kind: str = "movie"              # movie | series
    tmdb_id: int | None = None
    title: str = ""
    season: int | None = None
    disc_number: int | None = None
    upc: str = ""
    titles: list[ContribTitle] = []
    send: bool = False               # False: nur Vorschau


class ContribError(Exception):
    pass


def content_type(disc: dict) -> str:
    t = (disc.get("type") or "").lower()
    return "4k" if ("uhd" in t or "4k" in t) else ("blu-ray" if "blu" in t else "dvd")


def build(disc: dict, ids: dict, raw: list[str], req: ContribReq) -> tuple[dict, str]:
    if not ids.get("content_hash"):
        raise ContribError("Inhalts-Hash der Disc fehlt (Disc-Kennung nicht lesbar)")
    if req.kind not in ("movie", "series"):
        raise ContribError("Art muss Film oder Serie sein")
    by_id = {t["id"]: t for t in disc["titles"]}
    chosen = [t for t in req.titles if t.id in by_id and t.type in TYPES]
    if not chosen:
        raise ContribError("Mindestens einen Titel zuordnen")
    if req.kind == "movie" and not any(t.type == "MainMovie" for t in chosen):
        raise ContribError("Bei einem Film einen Titel als Hauptfilm markieren")
    if req.kind == "series" and not any(t.type == "Episode" and t.episode for t in chosen):
        raise ContribError("Bei einer Serie mindestens eine Folge mit Nummer angeben")
    titles = []
    for c in chosen:
        t = by_id[c.id]
        seg = t.get("segments") or ""
        titles.append({"index": t["id"], "source_filename": t.get("source") or None, "duration_seconds": int(t["duration"]), "size_bytes": t["bytes"],
                       "chapter_count": t.get("chapters"), "segment_count": len([s for s in seg.split(",") if s.strip()]) or None,
                       "segment_map": seg or None, "title_type": c.type,
                       "season": (c.season or (str(req.season) if req.season and c.type == "Episode" else "")) or None,
                       "episode": c.episode or None, "match_confidence": 1.0, "match_source": "manual"})
    payload = {"engram_version": f"makemkv-web {VERSION}", "export_version": "1", "exported_at": datetime.now(timezone.utc).isoformat(),
               "contribution_tier": 1,
               "disc": {"content_hash": ids["content_hash"], "volume_label": disc.get("volume") or disc.get("name") or "",
                        "content_type": content_type(disc), "disc_number": req.disc_number},
               "identification": {"tmdb_id": req.tmdb_id, "detected_title": req.title or None,
                                  "detected_season": (req.season or 1) if req.kind == "series" else None,
                                  "classification_source": "manual", "classification_confidence": 1.0},
               "titles": titles, "upc": re.sub(r"\D", "", req.upc) or None}
    return payload, "\n".join(raw) + "\n"


def _post(url: str, data: bytes, ctype: str, timeout: float = 30) -> tuple[int, bytes]:
    """Einzige Stelle mit Netzwerkzugriff (Tests ersetzen sie)."""
    r = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": ctype, "User-Agent": "makemkv-web", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        with e:
            return e.code, e.read()


async def submit(payload: dict, log: str) -> dict:
    h = payload["disc"]["content_hash"]
    try:
        st, body = await asyncio.to_thread(_post, f"{discdb.BASE}/api/engram/disc", json.dumps(payload).encode(), "application/json")
    except OSError as e:
        raise ContribError(f"TheDiscDB nicht erreichbar: {e}") from e
    if st != 200:
        raise ContribError(f"TheDiscDB lehnt ab ({st}): {body[:200].decode('utf-8', 'replace')}")
    res = json.loads(body or b"{}")
    log_ok = False
    if log.strip():
        try:
            st2, _ = await asyncio.to_thread(_post, f"{discdb.BASE}/api/engram/disc/{h}/logs/scan", log.encode(), "text/plain")
            log_ok = st2 == 200
        except OSError:
            pass
    return {"ok": True, "updated": bool(res.get("updated")), "log": log_ok}


# ---------------------------------------------------------------- Vorschlag für den Dialog
def _types_from_names(picks: list[int], names: dict, disc: dict) -> dict[int, dict]:
    by_id = {t["id"]: t for t in disc["titles"]}
    out, longest = {}, max(picks, key=lambda i: by_id[i]["duration"]) if picks else None
    for i in picks:
        m = _SE.search(names.get(i) or "")
        out[i] = {"type": "Episode", "season": str(int(m.group(1))), "episode": str(int(m.group(2)))} if m else \
                 {"type": "MainMovie" if i == longest else "Extra", "season": "", "episode": ""}
    return out


async def prefill(drive) -> dict:
    """Vorschlag: gemerkte Auswahl von Hand, sonst die Titelwahl des Headless-Modus; TMDB-Kennung, wenn bekannt."""
    disc, ids = drive.disc, await planner.get_ids(drive)
    picks, names, source, kind, tm, folder = [], {}, "", "", None, ""
    entry, _ = await memory.lookup(ids) if planner.ids_key(ids) else (None, "")
    m = memory.match(entry, disc) if entry else None
    if m and m["ok"]:
        picks, names, source, folder = m["picks"], m["names"], "gemerkte Auswahl von Hand", m["folder"]
    else:
        p = await planner.plan(drive)
        picks, names, source, tm = p["picks"], p["names"], p["source"], p.get("tmdb")
        kind = p["mode"] if p["mode"] in ("movie", "series") else ""
    types = _types_from_names(picks, names, disc)
    if p_series := any(v["type"] == "Episode" for v in types.values()):
        kind = "series"
    if kind == "series" and not p_series:
        types = {i: {"type": "Episode", "season": "", "episode": ""} for i in picks}
    if tm is None:
        info = await tmdbmatch.lookup(disc)
        tm = {k: info[k] for k in ("tmdb", "title", "year", "kind", "season")} if info else None
    kind = kind or (tm or {}).get("kind") or "movie"
    return {"kind": kind, "source": source, "ids": {k: ids.get(k) for k in ("disc_id", "content_hash", "format", "error")},
            "tmdb_id": int(tm["tmdb"]) if tm and str(tm.get("tmdb") or "").isdigit() else None, "title": (tm or {}).get("title") or re.sub(r"\s*\(\d{4}\)$", "", folder),
            "year": (tm or {}).get("year"), "season": (tm or {}).get("season") or (1 if kind == "series" else None),
            "titles": [{"id": i, **types[i], "name": names.get(i, "")} for i in picks], "log_lines": len(drive.scan_raw)}
