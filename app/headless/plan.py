"""Title choice for the disc in the drive, in this order:

1. Memory: the same disc was ripped by hand before (here or on another machine) – the same titles and names.
2. TheDiscDB (disc ID, then content hash): exactly the main feature or the episodes, names "Series S01E02 - Episode title".
3. TMDB runtimes (name of the disc, only if unambiguous): the title with the movie's runtime or the titles with the episode length.
4. Structure of the disc (choose.decide), the TMDB type as a cross-check.
"""
import asyncio
import re
from pathlib import Path

from app.config import DEV_DRIVE_DIR
from app.headless import choose, discdb, discid, memory, tmdbmatch, udf
from app.state import settings

_ids: dict[str, tuple[int, dict]] = {}          # drive -> (scan_id, identifiers)


def read_ids(dev: str) -> dict:
    """Read the disc identifiers from the device (development: image <drive>.iso next to the fake drive)."""
    path = f"{dev}.iso" if DEV_DRIVE_DIR else dev
    if DEV_DRIVE_DIR and not Path(path).exists():
        return {"error": "no image for the fake drive (development)"}
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
        ids = {"error": str(e) or "timeout"}
    _ids[drive.dev] = (drive.scan_id, ids)
    return ids


def cached_ids(drive) -> dict | None:
    hit = _ids.get(drive.dev) if drive else None
    return hit[1] if hit and hit[0] == drive.scan_id else None


def ids_key(ids: dict | None) -> str:
    return (ids or {}).get("disc_id") or (ids or {}).get("content_hash") or ""


# ---------------------------------------------------------------- names
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
        extra = _clean(p["item"]) if p.get("item") and _norm(p["item"]) != _norm(m["title"]) else (f"Version {k + 1}" if len(m["picks"]) > 1 else "")
        names[p["id"]] = base + (f" - {extra}" if extra else "")
    return base, names


def names_from_disc(disc: dict, ids: list[int]) -> dict[int, str]:
    """Like the interface (titles.js suggestName): with identical names append the title number."""
    out = {}
    for t in disc["titles"]:
        if t["id"] in ids:
            b = (t.get("name") or "").strip() or f"Title {t['id'] + 1}"
            dup = sum(1 for x in disc["titles"] if (x.get("name") or "").strip() == b) > 1
            out[t["id"]] = f"{b} - Title {t['id'] + 1:02d}" if dup else b
    return out


# ---------------------------------------------------------------- choice
async def plan(drive) -> dict:
    """{mode, source, picks, names, folder, reasons, ids, tmdb}. mode: memory|movie|series|unsure|manual."""
    disc, reasons = drive.disc, []
    ids = await get_ids(drive)
    if ids.get("error"):
        reasons.append(f"Disc identifier: {ids['error']}")
    out = {"ids": ids, "tmdb": None}
    if ids_key(ids):
        entry, where = await memory.lookup(ids)
        if entry:
            m = memory.match(entry, disc)
            if m["ok"]:
                names = {**names_from_disc(disc, m["picks"]), **{k: v for k, v in m["names"].items() if v}}
                return {**out, "mode": "memory", "source": f"Memory ({where})", "picks": m["picks"], "names": names,
                        "folder": m["folder"] or disc.get("name") or "", "reasons": [f"As last picked by hand: {len(m['picks'])} title{'s' if len(m['picks']) != 1 else ''}"] + reasons}
            reasons.append(f"Memory: {m['reason']}")
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
                what = "episode" if m["kind"] == "series" else "main feature"
                tm = {"tmdb": m.get("tmdb"), "title": m["title"], "year": m.get("year"), "kind": m["kind"]}
                return {**out, "tmdb": tm, "mode": m["kind"], "source": f"TheDiscDB ({via})", "picks": [p["id"] for p in m["picks"]], "names": names,
                        "folder": folder, "reasons": [f"TheDiscDB: \"{m['title']}\" ({m.get('year') or '?'}), {len(m['picks'])} × {what}"] + reasons}
            reasons.append(f"TheDiscDB: {m['reason']}")
        elif not any(r.startswith("TheDiscDB") for r in reasons):
            reasons.append("Disc not in TheDiscDB")
    prep = choose.prepare(disc)
    info = await tmdbmatch.lookup(disc)
    if info:
        out["tmdb"] = {k: info[k] for k in ("tmdb", "title", "year", "kind", "season")}
        tm = tmdbmatch.match(info, prep, disc)
        if tm["ok"]:
            names = {tm["picks"][0]: tm["folder"]} if info["kind"] == "movie" else names_from_disc(disc, tm["picks"])
            return {**out, "mode": info["kind"], "source": "TMDB (runtime)", "picks": tm["picks"], "names": names, "folder": tm["folder"],
                    "reasons": [tm["reason"]] + prep["reasons"] + reasons}
        reasons.append(tm["reason"])
    d = choose.decide(disc, ids.get("content_bytes") or 0, info["kind"] if info else "", prep)
    return {**out, "mode": d["mode"], "source": "Disc structure", "picks": d["picks"], "names": names_from_disc(disc, d["picks"]),
            "folder": disc.get("name") or disc.get("volume") or "", "reasons": d["reasons"] + reasons}


def skips(disc: dict, p: dict) -> list[list]:
    """Titles not taken with a short reason: [[title number, reason], …] (for display)."""
    pr = choose.prepare(disc)
    picks, mode, src = set(p.get("picks") or []), p.get("mode"), p.get("source") or ""
    out = []
    for t in disc.get("titles") or []:
        if t["id"] in picks:
            continue
        mins = f"{round(t['duration'] / 60)} min"
        if t["id"] in pr["dropped"]:
            why = "duplicate"
        elif t["id"] in pr["playall"]:
            why = "play-all"
        elif mode == "manual":
            why = "not ripped"
        elif src.startswith("TheDiscDB"):
            why = "according to TheDiscDB " + ("not an episode" if mode == "series" else "not the main feature")
        elif src.startswith("Memory"):
            why = "not picked by hand"
        elif src.startswith("TMDB"):
            why = "does not match the episode length" if mode == "series" else "does not match the movie runtime"
        elif mode == "series":
            why = "too short for an episode" if t["duration"] < choose.EP_MIN else "extra"
        elif mode == "movie":
            why = "shorter than the main feature"
        else:
            why = "not chosen"
        out.append([t["id"] + 1, f"{why}, {mins}"])
    return out
