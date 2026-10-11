"""Titelwahl für die Disc im Laufwerk, in dieser Reihenfolge:

1. Gedächtnis: dieselbe Disc wurde schon einmal von Hand gerippt (hier oder an einem anderen Rechner) – dieselben Titel und Namen.
2. TheDiscDB (Disc-ID, dann Inhalts-Hash): genau der Hauptfilm bzw. die Folgen, Namen „Serie S01E02 - Folgentitel“.
3. TMDB-Laufzeiten (Name der Disc, nur wenn eindeutig): der Titel mit der Filmlaufzeit bzw. die Titel mit Folgenlänge.
4. Struktur der Disc (choose.decide), TMDB-Art als Gegenprobe.
"""
import asyncio
import re
from pathlib import Path

from app.config import DEV_DRIVE_DIR
from app.headless import choose, discdb, discid, memory, tmdbmatch, udf
from app.state import settings

_ids: dict[str, tuple[int, dict]] = {}          # Laufwerk -> (scan_id, Kennungen)


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


async def get_ids(drive) -> dict:
    hit = _ids.get(drive.dev)
    if hit and hit[0] == drive.scan_id:
        return hit[1]
    try:
        ids = await asyncio.wait_for(asyncio.to_thread(read_ids, drive.dev), 120)
    except (OSError, udf.UdfError, asyncio.TimeoutError) as e:
        ids = {"error": str(e) or "Zeitüberschreitung"}
    _ids[drive.dev] = (drive.scan_id, ids)
    return ids


def cached_ids(drive) -> dict | None:
    hit = _ids.get(drive.dev) if drive else None
    return hit[1] if hit and hit[0] == drive.scan_id else None


def ids_key(ids: dict | None) -> str:
    return (ids or {}).get("disc_id") or (ids or {}).get("content_hash") or ""


# ---------------------------------------------------------------- Namen
def _norm(s: str) -> str:
    return re.sub(r"[^0-9a-zäöüß]+", "", (s or "").casefold())


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


# ---------------------------------------------------------------- Wahl
async def plan(drive) -> dict:
    """{mode, source, picks, names, folder, reasons, ids, tmdb}. mode: memory|movie|series|unsure|manual."""
    disc, reasons = drive.disc, []
    ids = await get_ids(drive)
    if ids.get("error"):
        reasons.append(f"Disc-Kennung: {ids['error']}")
    out = {"ids": ids, "tmdb": None}
    if ids_key(ids):
        entry, where = await memory.lookup(ids)
        if entry:
            m = memory.match(entry, disc)
            if m["ok"]:
                names = {**names_from_disc(disc, m["picks"]), **{k: v for k, v in m["names"].items() if v}}
                return {**out, "mode": "memory", "source": f"Gedächtnis ({where})", "picks": m["picks"], "names": names,
                        "folder": m["folder"] or disc.get("name") or "", "reasons": [f"Wie zuletzt von Hand gewählt: {len(m['picks'])} Titel"] + reasons}
            reasons.append(f"Gedächtnis: {m['reason']}")
    if settings.get("headless", {}).get("use_db", True) and ids_key(ids):
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
                tm = {"tmdb": m.get("tmdb"), "title": m["title"], "year": m.get("year"), "kind": m["kind"]}
                return {**out, "tmdb": tm, "mode": m["kind"], "source": f"TheDiscDB ({via})", "picks": [p["id"] for p in m["picks"]], "names": names,
                        "folder": folder, "reasons": [f"TheDiscDB: „{m['title']}“ ({m.get('year') or '?'}), {len(m['picks'])} × {what}"] + reasons}
            reasons.append(f"TheDiscDB: {m['reason']}")
        elif not any(r.startswith("TheDiscDB") for r in reasons):
            reasons.append("Disc nicht in TheDiscDB")
    prep = choose.prepare(disc)
    info = await tmdbmatch.lookup(disc)
    if info:
        out["tmdb"] = {k: info[k] for k in ("tmdb", "title", "year", "kind", "season")}
        tm = tmdbmatch.match(info, prep, disc)
        if tm["ok"]:
            names = {tm["picks"][0]: tm["folder"]} if info["kind"] == "movie" else names_from_disc(disc, tm["picks"])
            return {**out, "mode": info["kind"], "source": "TMDB (Laufzeit)", "picks": tm["picks"], "names": names, "folder": tm["folder"],
                    "reasons": [tm["reason"]] + prep["reasons"] + reasons}
        reasons.append(tm["reason"])
    d = choose.decide(disc, ids.get("content_bytes") or 0, info["kind"] if info else "", prep)
    return {**out, "mode": d["mode"], "source": "Struktur der Disc", "picks": d["picks"], "names": names_from_disc(disc, d["picks"]),
            "folder": disc.get("name") or disc.get("volume") or "", "reasons": d["reasons"] + reasons}
