"""Erkennung samt TMDB-Abgleich: aus einer Auswahl von Dateien einen Vorschlag für den Assistenten machen."""
import re
from difflib import SequenceMatcher

from app.media import conf, detect, metadata, scan, series

_norm = lambda s: re.sub(r"[^a-z0-9äöüß]+", "", (s or "").lower())      # noqa: E731


def best_match(cands: list[dict], title: str, year: int | None) -> tuple[dict | None, float]:
    """Treffer mit dem ähnlichsten Titel (Titel oder Originaltitel), Jahr zählt mit. Rückgabe (Treffer, Ähnlichkeit 0–1)."""
    best, score = None, 0.0
    for c in cands:
        r = max(SequenceMatcher(None, _norm(title), _norm(c["title"])).ratio(), SequenceMatcher(None, _norm(title), _norm(c["original"])).ratio())
        if year and c["year"] == year:
            r += 0.05
        if r > score:
            best, score = c, r
    return (best, min(score, 1.0)) if best and score >= 0.6 else (None, 0.0)


def start_episode(det: dict, season: int, n_eps: int) -> dict:
    k = series.key(det["title"], det["year"], det.get("tmdb"))
    known = series.next_episode(k, season, det.get("disc"))
    if known:
        return {"episode": known, "known": True, "estimated": False}
    disc = det.get("disc") or 1
    if disc > 1:
        return {"episode": (disc - 1) * max(n_eps, 1) + 1, "known": False, "estimated": True}
    return {"episode": 1, "known": False, "estimated": False}


async def episodes_for(items: list[dict], season: int, start: int, tmdb: int | None, key: str, lang: str) -> dict:
    """Staffel/Episode je Episodentitel; mit TMDB-Folgenliste samt Namen und Laufzeit-Abgleich. {assigned, episode_list, error}."""
    tm_eps, err = [], ""
    if tmdb and key:
        try:
            tm_eps = await metadata.season(key, tmdb, season, lang)
        except metadata.MetadataError as e:
            err = str(e)
    return {"assigned": detect.assign_episodes(items, season, start, tm_eps), "episode_list": tm_eps, "error": err}


async def analyze(paths: list[str]) -> dict:
    st = conf.cfg()
    files_ = await scan.describe(paths)
    det = detect.detect([dict(f) for f in files_])
    key, lang = st["tmdb_key"], st["language"]
    tm = {"available": bool(key), "error": "", "candidates": [], "chosen": None, "similarity": 0.0}
    if key and det["kind"] in ("movie", "series") and det["title"]:
        kind = "movie" if det["kind"] == "movie" else "tv"
        try:
            cands = await metadata.search(key, kind, det["title"], det["year"], lang)
            if not cands and det["year"]:
                cands = await metadata.search(key, kind, det["title"], None, lang)
            tm["candidates"] = cands[:5]
            hit, score = best_match(cands, det["title"], det["year"])
            if hit:
                tm["chosen"] = await metadata.details(key, kind, hit["tmdb"], lang)
                tm["similarity"] = round(score, 2)
                det["confidence"] = round(min(0.98, det["confidence"] + (0.05 if score >= 0.85 else 0.0) + (0.03 if hit["year"] == det["year"] else 0.0)), 2)
                det["reasons"].append(f"TMDB-Treffer „{hit['title']}“ ({hit['year']})")
        except metadata.MetadataError as e:
            tm["error"] = str(e)
    out = {"detect": det, "tmdb": tm, "files": files_, "episodes": None, "start": None}
    if det["kind"] == "series":
        n_eps = sum(1 for i in det["items"] if i["role"] == "episode")
        chosen = tm["chosen"] or {}
        d2 = {**det, "tmdb": chosen.get("tmdb")}
        out["start"] = start_episode(d2, det["season"], n_eps)
        out["episodes"] = await episodes_for(det["items"], det["season"], out["start"]["episode"], chosen.get("tmdb"), key, lang)
        deltas = [a["delta"] for a in out["episodes"]["assigned"] if a["delta"] is not None]
        if deltas and max(abs(x) for x in deltas) <= 6:
            det["confidence"] = round(min(0.98, det["confidence"] + 0.03), 2)
            det["reasons"].append("Laufzeiten passen zu den TMDB-Folgen")
    return out
