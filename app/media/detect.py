"""Erkennen, was ein Titel/Ordner ist: Film oder Serie, Titel, Jahr, Staffel, Disc – samt Play-All-Titeln.

Reine Funktionen ohne Dateizugriff und Netzwerk. Eingabe sind Dateien mit Laufzeit (aus der Bibliothek bzw. der Begleitdatei beim Rippen);
das Ergebnis enthält die Trefferwahrscheinlichkeit (0–1) und die Gründe als lesbare Sätze.
"""
import re
from datetime import date
from statistics import median

from app.media.naming import split_name

EP_MIN, EP_MAX = 15 * 60, 80 * 60          # Länge einer Serienfolge (Sekunden)
MOVIE_MIN = 70 * 60                        # ab hier ist es ein Hauptfilm
NOISE = re.compile(r"\b(2160p|1080p|1080i|720p|576p|480p|uhd|bluray|blu-ray|bdrip|brrip|dvdrip|dvd|remux|x264|x265|h264|h265|hevc|avc|ac3|dts|"
                   r"german|deutsch|multi|proper|extended|remastered|disc ?image|bd|hdr)\b", re.I)
_YEAR = re.compile(r"[\(\[]?\b((?:19|20)\d{2})\b[\)\]]?")
_SEASON = re.compile(r"\b(?:season|staffel|series|serie|saison)\s*0*(\d{1,2})\b|\bS0*(\d{1,2})\b(?!\s*E\d)", re.I)
_DISC = re.compile(r"\b(?:disc|disk|dvd|cd|bd)\s*0*(\d{1,2})\b|\bD0*(\d{1,2})\b", re.I)
_TITLENO = re.compile(r"(?:titel|title|track|t)[ _.-]*0*(\d{1,3})$", re.I)


def analyze_name(raw: str) -> dict:
    """Aus Disc-Name, Volume-Label, Ordner- oder Dateinamen Titel, Jahr, Staffel und Disc-Nummer lesen
    („WALKING_DEAD_S1_D1“ -> Walking Dead, S1, D1)."""
    s = re.sub(r"\.(mkv|mp4|m4v|avi|iso|m2ts)$", "", raw.strip(), flags=re.I)
    s = s.replace("_", " ")
    if " " not in s:
        s = s.replace(".", " ")
    out = {"title": "", "year": None, "season": None, "disc": None, "title_no": None}
    m = _TITLENO.search(s.strip())
    if m:
        out["title_no"] = int(m.group(1))
        s = s[:m.start()]
    ym = None
    for m in _YEAR.finditer(s):
        if int(m.group(1)) <= date.today().year + 1:   # „Blade Runner 2049“: kein Erscheinungsjahr
            ym = m
    if ym and ym.start() > 0:                          # Jahr nur, wenn davor ein Titel steht („2012“ allein ist der Titel)
        out["year"] = int(ym.group(1))
        s = s[:ym.start()] + " " + s[ym.end():]
    sm = _SEASON.search(s)
    if sm:
        out["season"] = int(sm.group(1) or sm.group(2))
        s = s[:sm.start()] + " " + s[sm.end():]
    dm = _DISC.search(s)
    if dm:
        out["disc"] = int(dm.group(1) or dm.group(2))
        s = s[:dm.start()] + " " + s[dm.end():]
    s = NOISE.sub(" ", s)
    s = re.sub(r"[\[\(]\s*[\]\)]", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" -–:,._")
    if s and s == s.upper() and any(c.isalpha() for c in s):
        s = s.title()
    out["title"] = s
    return out


def find_playall(durs: list[float]) -> dict[int, list[int]]:
    """Index eines Play-All-Titels -> Indizes der Titel, deren Laufzeiten sich zu seiner Laufzeit addieren (fortlaufende Reihe, ≥ 2)."""
    res: dict[int, list[int]] = {}
    for i, d in enumerate(durs):
        if d < 25 * 60:
            continue
        others = [j for j in range(len(durs)) if j != i and durs[j] >= 5 * 60]
        tol = max(60, 0.015 * d)
        for a in range(len(others)):
            s = 0.0
            for b in range(a, len(others)):
                s += durs[others[b]]
                if b > a and abs(s - d) <= tol:
                    res[i] = others[a:b + 1]
                    break
                if s > d + tol:
                    break
            if i in res:
                break
    return res


def _fmt(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


def _sources(files: list[dict]) -> list[tuple[str, str]]:
    """Namensquellen in der Reihenfolge ihrer Verlässlichkeit: Disc-Name, Volume-Label, Ordner, Dateiname."""
    out = []
    for f in files:
        d = f.get("disc") or {}
        if d.get("name"):
            out.append(("Disc-Name", d["name"]))
        if d.get("volume"):
            out.append(("Disc-Label", d["volume"]))
    parts = files[0]["path"].split("/")
    if len(parts) > 1:
        out.append(("Ordnername", parts[-2]))
    out.append(("Dateiname", parts[-1]))
    seen, uniq = set(), []
    for k, v in out:
        if v not in seen:
            seen.add(v)
            uniq.append((k, v))
    return uniq


def detect(files: list[dict]) -> dict:
    """files: [{path, dur, size, disc?: {name, volume, titles:[{id, duration}]}, title_id?}] (alle zu einem Medium).
    Ergebnis: {kind: movie|series|unknown, title, year, season, disc, confidence, reasons, items:[{path, dur, role, order, playall_of?}]}."""
    if not files:
        return {"kind": "unknown", "title": "", "year": None, "season": None, "disc": None, "confidence": 0.0, "reasons": [], "items": []}
    for f in files:
        a = analyze_name(f["path"].split("/")[-1])
        f["_no"] = f.get("title_id") if f.get("title_id") is not None else a["title_no"]
    files = sorted(files, key=lambda f: (f["_no"] is None, f["_no"] or 0, f["path"].lower()))
    reasons, conf = [], 0.0
    # Namen: erste Quelle mit brauchbarem Titel; Staffel/Disc/Jahr aus allen Quellen
    info = {"title": "", "year": None, "season": None, "disc": None}
    title_src = ""
    for src, raw in _sources(files):
        a = analyze_name(raw)
        if not info["title"] and a["title"] and not re.fullmatch(r"(titel|title|track)?\s*\d*", a["title"], re.I):
            info["title"], title_src = a["title"], src
        for k in ("year", "season", "disc"):
            if info[k] is None and a[k] is not None:
                info[k] = a[k]
    if not info["title"] and files[0]["path"]:
        info["title"] = split_name(files[0]["path"].split("/")[-1].rsplit(".", 1)[0])["title"]
    if title_src in ("Disc-Name", "Disc-Label", "Ordnername"):
        conf += 0.1
    # Laufzeiten, Play-All
    durs = [float(f.get("dur") or 0) for f in files]
    disc = next((f["disc"] for f in files if f.get("disc") and f["disc"].get("titles")), None)
    playall: dict[int, list[int]] = {}
    if disc:
        ids = {t["id"]: float(t.get("duration") or 0) for t in disc["titles"]}
        order = sorted(ids)
        pa = find_playall([ids[i] for i in order])
        for idx, members in pa.items():
            for k, f in enumerate(files):
                if f.get("title_id") == order[idx]:
                    playall[k] = [order[m] for m in members]
    else:
        playall = find_playall(durs) if len(files) > 2 else {}
    items = [{"path": f["path"], "dur": durs[k], "role": "", "order": k, "size": f.get("size", 0), "title_id": f.get("title_id")} for k, f in enumerate(files)]
    for k in playall:
        items[k]["role"] = "playall"
        items[k]["playall_of"] = playall[k]
        reasons.append(f"Play-All erkannt ({_fmt(durs[k])}, Summe mehrerer Titel)")
    rest = [k for k in range(len(files)) if k not in playall and durs[k] > 0]
    eps = [k for k in rest if EP_MIN <= durs[k] <= EP_MAX]
    med = median(durs[k] for k in eps) if eps else 0
    cluster = [k for k in eps if 0.6 * med <= durs[k] <= 1.5 * med] if eps else []
    longest = max(rest, key=lambda k: durs[k]) if rest else None
    kind = "unknown"
    if len(cluster) >= 2 or (len(cluster) == 1 and (info["season"] or info["disc"]) and not (longest is not None and durs[longest] >= MOVIE_MIN)):
        kind = "series"
        conf += 0.35 + (0.1 if len(cluster) >= 4 else 0) + (0.1 if len(cluster) < 2 else 0.05)
        reasons.insert(0, f"{len(cluster)} Titel à {int(min(durs[k] for k in cluster) // 60)}–{int(max(durs[k] for k in cluster) // 60)} min (Serienfolgen)")
        if info["season"] or info["disc"]:
            conf += 0.15
            reasons.append("Staffel/Disc im Namen" + (f" (Staffel {info['season']})" if info["season"] else "") + (f" (Disc {info['disc']})" if info["disc"] else ""))
        if playall:
            conf += 0.1
        for k in rest:
            items[k]["role"] = "episode" if (k in cluster or (cluster and durs[k] <= 2.2 * med and durs[k] >= 0.6 * med)) else "extra"
        for k in rest:
            if items[k]["role"] == "episode" and k not in cluster:
                items[k]["long"] = True
    elif longest is not None and durs[longest] >= MOVIE_MIN:
        kind = "movie"
        conf += 0.5
        reasons.insert(0, f"Haupttitel von {_fmt(durs[longest])}")
        if info["year"]:
            conf += 0.2
            reasons.append(f"Jahr {info['year']} im Namen")
        big = [k for k in rest if durs[k] >= MOVIE_MIN]
        if len(big) > 1:
            conf -= 0.25
            reasons.append(f"{len(big)} lange Titel – mehrere Filme oder Fassungen?")
        for k in rest:
            items[k]["role"] = "movie" if k == longest else ("extra" if durs[k] < MOVIE_MIN else "movie")
        if any(items[k]["role"] == "extra" for k in rest):
            reasons.append("kürzere Titel gelten als Extras")
            conf += 0.03
    elif len(files) and not rest:                                   # keine Laufzeiten bekannt: nur der Name
        has_ep = bool(re.search(r"[Ss]\d{1,2}[ ._-]?[Ee]\d{1,3}", files[0]["path"]))
        kind = "series" if (has_ep or info["season"]) else "unknown"
        conf += 0.25 if kind == "series" else 0.0
        for it in items:
            it["role"] = "episode" if kind == "series" else ""
    else:
        for k in rest:
            items[k]["role"] = "extra"
    if title_src:
        reasons.append(f"{title_src} „{dict(_sources(files))[title_src]}“")
    if disc:
        conf += 0.05
    for it in items:
        if not it["role"]:
            it["role"] = "extra" if kind != "unknown" else ""
    return {"kind": kind, "title": info["title"], "year": info["year"], "season": info["season"] or (1 if kind == "series" else None),
            "disc": info["disc"], "confidence": round(max(0.0, min(conf, 0.97)), 2), "reasons": reasons, "items": items}


def assign_episodes(items: list[dict], season: int, start: int, tmdb_eps: list[dict] | None = None) -> list[dict]:
    """Staffel/Episode je Episoden-Titel vorschlagen: fortlaufend ab `start`. Mit TMDB-Folgen (`[{n, name, runtime}]`) kommen Namen und der
    Laufzeit-Abgleich dazu; ein Titel, der etwa so lang ist wie zwei aufeinanderfolgende Folgen, wird als Doppelfolge gezählt.
    Rückgabe: je Item mit Rolle „episode“ {path, season, episodes, name, runtime, delta}; `delta` in Minuten (None = unbekannt)."""
    by_n = {e["n"]: e for e in (tmdb_eps or [])}
    out, n = [], start
    for it in items:
        if it["role"] != "episode":
            continue
        mins = it["dur"] / 60
        eps = [n]
        rt = (by_n.get(n) or {}).get("runtime")
        nxt = (by_n.get(n + 1) or {}).get("runtime")
        if rt and nxt and abs(mins - (rt + nxt)) < abs(mins - rt) and abs(mins - (rt + nxt)) <= 0.12 * (rt + nxt):
            eps = [n, n + 1]
            rt = rt + nxt
        name = " & ".join(str((by_n.get(e) or {}).get("name") or "") for e in eps if (by_n.get(e) or {}).get("name"))
        out.append({"path": it["path"], "season": season, "episodes": eps, "name": name, "runtime": rt, "delta": round(mins - rt, 1) if rt else None})
        n = eps[-1] + 1
    return out
