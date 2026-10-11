"""TMDB als zweite Stufe, wenn TheDiscDB die Disc nicht kennt (z. B. deutsche Ausgaben): Name der Disc suchen, Laufzeiten abgleichen.

Nur ein eindeutiger Name zählt (genau gleicher Titel unter den ersten drei Treffern, und nur als Film oder nur als Serie).
Film: genau ein Titel, dessen Länge zur TMDB-Laufzeit passt (± 4 %, mindestens ± 3 min). Serie: die Titel, deren Länge zu den
Folgen der Staffel passt (± 12 %, mindestens ± 2 min), mindestens zwei. Sonst entscheidet die Struktur (choose.decide) mit dem
gefundenen Namen als Gegenprobe.
"""
import re

from app.media import detect

MIN_MOVIE = 40 * 60


def _norm(s: str) -> str:
    return re.sub(r"[^0-9a-zäöüß]+", "", (s or "").casefold())


async def lookup(disc: dict) -> dict | None:
    """{kind: movie|series, tmdb, title, year, runtime, season, episodes: [Minuten]} oder None (kein Schlüssel, kein eindeutiger Name)."""
    try:
        from app.media import conf, metadata
    except ImportError:
        return None
    st = conf.cfg()
    key, lang = st.get("tmdb_key"), st.get("language") or "de-DE"
    if not key:
        return None
    a = detect.analyze_name(disc.get("name") or disc.get("volume") or "")
    if len(a["title"]) < 2:
        return None
    exact = {}
    try:
        for kind in ("movie", "tv"):
            hits = await metadata.search(key, kind, a["title"], a["year"], lang)
            exact[kind] = [h for h in hits[:3] if _norm(a["title"]) in (_norm(h["title"]), _norm(h["original"]))]
        if bool(exact["movie"]) == bool(exact["tv"]):
            return None
        if exact["movie"]:
            h = exact["movie"][0]
            d = await metadata.details(key, "movie", h["tmdb"], lang)
            return {"kind": "movie", "tmdb": h["tmdb"], "title": h["title"], "year": h["year"], "runtime": d.get("runtime") or 0, "season": None,
                    "episodes": []}
        h = exact["tv"][0]
        season = a["season"] or 1
        eps = [e["runtime"] for e in await metadata.season(key, h["tmdb"], season, lang) if e.get("runtime")]
        if not eps:
            d = await metadata.details(key, "tv", h["tmdb"], lang)
            eps = [d["runtime"]] if d.get("runtime") else []
        return {"kind": "series", "tmdb": h["tmdb"], "title": h["title"], "year": h["year"], "runtime": 0, "season": season, "episodes": eps}
    except Exception:  # noqa: BLE001  (Netz, Schlüssel, nicht gefunden: dann ohne TMDB)
        return None


def match(info: dict, prep: dict, disc: dict) -> dict:
    """info: aus lookup(); prep: choose.prepare(). {ok, mode, picks, reason, folder}."""
    rest = prep["rest"]
    base = info["title"] + (f" ({info['year']})" if info.get("year") else "")
    res = {"ok": False, "mode": info["kind"], "picks": [], "reason": "", "folder": base}
    if info["kind"] == "movie":
        rt = info.get("runtime") or 0
        if not rt:
            res["reason"] = f"TMDB: „{base}“ ohne Laufzeit"
            return res
        c = [t for t in rest if t["duration"] >= MIN_MOVIE and abs(t["duration"] / 60 - rt) <= max(3, 0.04 * rt)]
        if len(c) != 1:
            res["reason"] = f"TMDB: Laufzeit von „{base}“ ({rt} min) passt zu {len(c) or 'keinem'} Titel{'n' if len(c) > 1 else ''}"
            return res
        res.update(ok=True, picks=[c[0]["id"]],
                   reason=f"TMDB: „{base}“, {rt} min – passt zu Titel {c[0]['id'] + 1} ({c[0].get('duration_text') or int(c[0]['duration'] // 60)})")
        return res
    rts = info.get("episodes") or []
    c = [t for t in rest if t["duration"] >= 5 * 60 and any(abs(t["duration"] / 60 - r) <= max(2, 0.12 * r) for r in rts)]
    a = detect.analyze_name(disc.get("name") or disc.get("volume") or "")
    res["folder"] = base + f" - Staffel {info['season']}" + (f" Disc {a['disc']}" if a.get("disc") else "")
    if not rts or len(c) < 2:
        res["reason"] = f"TMDB: Folgenlängen von „{base}“ passen zu {len(c) or 'keinem'} Titel{'n' if len(c) > 1 else ''}"
        return res
    lo, hi = min(rts), max(rts)
    res.update(ok=True, picks=[t["id"] for t in c],
               reason=f"TMDB: „{base}“ Staffel {info['season']}, Folgen {lo}{'–' + str(hi) if hi != lo else ''} min – {len(c)} Titel passen")
    return res
