"""Title choice without a database match: detect from the disc's structure whether it is a movie or a series.

Pure functions (no network, no file access). Principle: something is selected only if the structure is unambiguous
(movie: the main feature, series: the episodes). Otherwise "unsure": all titles except duplicates and play-all – as long as that is not more than
twice the disc's video data (protection against discs with hundreds of fake playlists); beyond that "by hand".
"""
from app.media import detect

MOVIE_MIN = detect.MOVIE_MIN
EP_MIN, EP_MAX = detect.EP_MIN, detect.EP_MAX
CAPACITY = {"dvd": 8.5e9, "bluray": 50e9, "uhd": 100e9}     # fallback if the size of the video data is unknown
LIMIT_FACTOR = 2.0


def disc_kind(disc: dict) -> str:
    t = (disc.get("type") or "").lower()
    if "uhd" in t or "4k" in t:
        return "uhd"
    return "bluray" if "blu" in t else "dvd"


def dedupe(titles: list[dict]) -> tuple[list[dict], list[int]]:
    """Keep titles with the same runtime, size and the same segments (order does not matter) only once (the first).
    Episodes of a DVD differ in size and stay; fake playlists made of the same segments drop out."""
    seen, kept, dropped = set(), [], []
    for t in sorted(titles, key=lambda x: x["id"]):
        seg = ",".join(sorted(s.strip() for s in (t.get("segments") or "").split(",") if s.strip()))
        key = (int(t["duration"]) // 2, t["bytes"], seg)
        if t["bytes"] and key in seen:
            dropped.append(t["id"])
            continue
        seen.add(key)
        kept.append(t)
    return kept, dropped


def _consistent(durs: list[float], ratio: float = 1.35) -> bool:
    return len(durs) >= 2 and min(durs) > 0 and max(durs) / min(durs) <= ratio


def _segs(t: dict) -> list[str]:
    return [x.strip() for x in (t.get("segments") or "").split(",") if x.strip()]


def segment_playall(titles: list[dict]) -> dict[int, list[int]]:
    """Blu-ray: play-all = a title whose segments contain the segments of at least two other titles and whose length is their sum
    (Vikings: 00803.mpls = 800,801,802). Lengths that match by chance no longer count that way."""
    out = {}
    for t in titles:
        st = set(_segs(t))
        if len(st) < 2:
            continue
        mem = [o for o in titles if o["id"] != t["id"] and _segs(o) and set(_segs(o)) <= st and len(set(_segs(o))) < len(st)]
        if len(mem) >= 2 and abs(sum(o["duration"] for o in mem) - t["duration"]) <= max(60, 0.03 * t["duration"]):
            out[t["id"]] = sorted(o["id"] for o in mem)
    return out


def prepare(disc: dict) -> dict:
    """Sort out duplicates and play-all, roles from detect. {titles, kept, dropped, playall, rest, det, role, reasons}."""
    titles = [t for t in disc.get("titles") or [] if t.get("duration")]
    kept, dropped = dedupe(titles)
    reasons = []
    if dropped:
        reasons.append(f"{len(dropped)} duplicate titles sorted out")
    name = disc.get("name") or disc.get("volume") or "Disc"
    files = [{"path": f"{name}/Title {t['id'] + 1:02d}.mkv", "dur": t["duration"], "size": t["bytes"], "title_id": t["id"],
              "disc": {"name": disc.get("name", ""), "volume": disc.get("volume", ""), "titles": kept}} for t in kept]
    det = detect.detect(files) if files else {"kind": "unknown", "items": [], "season": None, "disc": None}
    role = {it["title_id"]: it for it in det["items"]}
    members: list[int] = []
    if disc_kind(disc) != "dvd" and kept and all(_segs(t) for t in kept):     # Blu-ray: segments are unambiguous, the runtime alone is not
        pa = segment_playall(kept)
        playall = sorted(pa)
        members = sorted({m for ms in pa.values() for m in ms if m not in pa})
        for i, it in role.items():
            if it["role"] == "playall" and i not in pa:
                it["role"] = "episode" if EP_MIN <= it["dur"] <= EP_MAX else "extra"
    else:
        playall = [i for i, it in role.items() if it["role"] == "playall"]
    if playall:
        reasons.append(f"Play-all detected (title{'s' if len(playall) > 1 else ''} {', '.join(str(i + 1) for i in playall)})")
    rest = [t for t in kept if t["id"] not in playall]
    return {"titles": titles, "kept": kept, "dropped": dropped, "playall": playall, "members": members, "rest": rest, "det": det, "role": role,
            "reasons": reasons}


def decide(disc: dict, content_bytes: int = 0, hint: str = "", prep: dict | None = None) -> dict:
    """disc: as in /api/state (titles with id, duration, bytes, segments). hint: "movie"/"series" from TMDB (or empty).
    Result: {mode: movie|series|unsure|manual, picks: [ids], reasons: [..], playall: [ids], dropped: [ids], total, limit}."""
    pr = prep or prepare(disc)
    titles, rest, det, role, playall, dropped = pr["titles"], pr["rest"], pr["det"], pr["role"], pr["playall"], pr["dropped"]
    reasons = list(pr["reasons"])
    by_id = {t["id"]: t for t in titles}
    longs = [t for t in rest if t["duration"] >= MOVIE_MIN]
    mem = [t for t in rest if t["id"] in pr.get("members", [])]
    # A play-all that is shorter than the longest title combines extras (Jumanji: 45 min bonus next to a 104 min movie)
    bonus = bool(mem and longs) and max(t["duration"] for t in longs) > max(by_id[i]["duration"] for i in playall)
    eps = [t for t in rest if role.get(t["id"], {}).get("role") == "episode" and t["duration"] < MOVIE_MIN]
    mids = [t for t in rest if EP_MIN <= t["duration"] <= EP_MAX and t not in longs and not (bonus and t in mem)]
    series_like = len(mids) >= 3 and _consistent([t["duration"] for t in mids])
    same = 0 < len(longs) <= 3 and max(t["duration"] for t in longs) <= 1.03 * min(t["duration"] for t in longs)   # versions of one movie
    marker = any(detect.analyze_name(n or "")[k] for n in (disc.get("name"), disc.get("volume")) for k in ("season", "disc"))   # the name only
    mode, picks = "unsure", []
    if len(mem) >= 2 and hint != "movie" and not bonus and all(t["duration"] < MOVIE_MIN for t in mem):
        mode, picks = "series", [t["id"] for t in mem]
        reasons.insert(0, f"Series: {len(mem)} episodes from the play-all")
    elif (det["kind"] == "series" and len(eps) >= 2 and (_consistent([t["duration"] for t in eps]) or len(eps) >= 3)
            and not longs and hint != "movie"):
        mode, picks = "series", [t["id"] for t in eps]
        reasons.insert(0, f"Series: {len(eps)} episodes of {int(min(t['duration'] for t in eps) // 60)}–{int(max(t['duration'] for t in eps) // 60)} min")
    elif same and not series_like and not marker and hint != "series":
        mode, picks = "movie", [t["id"] for t in longs]
        txt = longs[0]["duration_text"] or int(longs[0]["duration"] // 60)
        reasons.insert(0, f"Movie: one main title ({txt}), the rest shorter" if len(longs) == 1
                       else f"Movie: {len(longs)} versions of the main title of equal length ({txt}), the rest shorter")
        if bonus:
            reasons.append("Play-all shorter than the movie – combines extras")
    else:
        why = []
        if len(longs) > 1 and not same:
            why.append(f"{len(longs)} titles of different lengths")
        if longs and series_like:
            why.append("main feature and several titles of equal length")
        if not longs and len(eps) < 2:
            why.append("neither a main feature nor episodes recognizable")
        if marker and longs and same:
            why.append("name points to a series")
        if hint:
            why.append(f"TMDB knows the name as a {'movie' if hint == 'movie' else 'series'}")
        reasons.insert(0, "Unsure" + (f": {', '.join(why)}" if why else ""))
        picks = [t["id"] for t in rest]
    total = sum(by_id[i]["bytes"] for i in picks)
    limit = int(LIMIT_FACTOR * (content_bytes or CAPACITY[disc_kind(disc)]))
    if mode == "unsure" and total > limit:
        reasons.append(f"{total / 1e9:.1f} GB altogether – more than twice the disc ({limit / 1e9:.1f} GB); please choose by hand")
        mode, picks = "manual", []
    return {"mode": mode, "picks": picks, "reasons": reasons, "playall": playall, "dropped": dropped, "total": total, "limit": limit}
