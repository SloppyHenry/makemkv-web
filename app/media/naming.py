"""Naming after the Jellyfin scheme (pure functions, without file access).

Rules from the Jellyfin documentation (as of 2026-10, https://jellyfin.org/docs/general/server/media/movies/ and .../shows/):
- Movie: `Title (Year) [imdbid-tt…]/Title (Year) [imdbid-tt…].mkv`; further versions with a separator and the name after it (`… - 1080p.mkv`);
  extras in subfolders (extras, behind the scenes, deleted scenes, featurettes, interviews, scenes, shorts, trailers …).
- Series: `Series (Year) [tmdbid-…]/Season 01/Series S01E01.mkv`; double episodes `S01E01-E02`; the episode name may follow;
  specials in `Season 00`; never abbreviate "Season", number with a leading zero.
- Not allowed in names: < > : " / \\ | ? *  (replaced or removed here), no dot or space at the end.
"""
import re
import unicodedata

EXTRA_DIRS = ("extras", "behind the scenes", "deleted scenes", "featurettes", "interviews", "scenes", "shorts", "trailers", "samples", "clips", "other")
VIDEO_EXT = (".mkv", ".mp4", ".m4v", ".avi", ".m2ts", ".iso")


def clean_part(s: str, maxlen: int = 120) -> str:
    """Make a name part fit for the file system (umlauts and other letters stay)."""
    s = unicodedata.normalize("NFC", s or "")
    s = re.sub(r"[\x00-\x1f]", "", s)
    s = re.sub(r"\s*:\s*", " - ", s)                 # "Star Trek: Voyager" -> "Star Trek - Voyager"
    s = s.replace('"', "'")
    s = re.sub(r"[?*<>]", "", s)
    s = re.sub(r"\s*[/\\|]\s*", " - ", s)
    s = re.sub(r"(?:\s-\s){2,}", " - ", s)
    s = re.sub(r"\s+", " ", s).strip(" .-")
    return s[:maxlen].rstrip(" .-")


def id_tag(imdb: str | None = None, tmdb: int | str | None = None, prefer: str = "imdb") -> str:
    """`[imdbid-tt0133093]` or `[tmdbid-603]`; empty if no ID is known."""
    imdb = (imdb or "").strip()
    imdb = imdb if re.fullmatch(r"tt\d{6,10}", imdb) else ""
    tmdb = str(tmdb or "").strip()
    tmdb = tmdb if tmdb.isdigit() else ""
    order = [("imdbid", imdb), ("tmdbid", tmdb)] if prefer == "imdb" else [("tmdbid", tmdb), ("imdbid", imdb)]
    for name, val in order:
        if val:
            return f"[{name}-{val}]"
    return ""


def media_name(title: str, year: int | str | None = None, imdb=None, tmdb=None, tags: bool = True, prefer: str = "imdb") -> str:
    """`Title (Year) [imdbid-tt…]` – year and ID only if known (and the ID only with `tags`)."""
    name = clean_part(title) or "Untitled"
    if str(year or "").isdigit():
        name += f" ({int(year)})"
    tag = id_tag(imdb, tmdb, prefer) if tags else ""
    return f"{name} {tag}" if tag else name


def movie_rel(title, year, ext, imdb=None, tmdb=None, tags=True, version: str = "", extra: str = "", extra_name: str = "") -> str:
    """Relative path of a movie below the movies folder.
    `version` (e.g. "1080p", "Director's Cut") appends the version; `extra` (a name from EXTRA_DIRS) puts the file into an extras subfolder."""
    folder = media_name(title, year, imdb, tmdb, tags, "imdb")
    if extra:
        extra = extra if extra in EXTRA_DIRS else "extras"
        return f"{folder}/{extra}/{clean_part(extra_name, 150) or 'Extra'}{ext}"
    ver = f" - {clean_part(version, 40)}" if clean_part(version, 40) else ""
    return f"{folder}/{folder}{ver}{ext}"


def season_folder(season: int) -> str:
    return f"Season {int(season):02d}"


def episode_code(season: int, episodes: list[int]) -> str:
    """`S01E01` or `S01E01-E02` for double episodes (consecutive)."""
    eps = sorted(set(int(e) for e in episodes))
    if not eps or eps[0] < 0:
        raise ValueError("no episode")
    if eps != list(range(eps[0], eps[-1] + 1)):
        raise ValueError("the episodes of one file must be consecutive")
    code = f"S{int(season):02d}E{eps[0]:02d}"
    return code + (f"-E{eps[-1]:02d}" if len(eps) > 1 else "")


def series_folder(title, year=None, imdb=None, tmdb=None, tags=True) -> str:
    return media_name(title, year, imdb, tmdb, tags, "tmdb")


def episode_rel(title, year, season: int, episodes: list[int], ext: str, imdb=None, tmdb=None, tags=True, ep_name: str = "") -> str:
    """Relative path of an episode below the series folder: `Series (Year) [tmdbid-…]/Season 01/Series S01E01 - Name.mkv`."""
    base = f"{clean_part(title) or 'Untitled'} {episode_code(season, episodes)}"
    name = clean_part(ep_name, 100)
    if name:
        base += f" - {name}"
    return f"{series_folder(title, year, imdb, tmdb, tags)}/{season_folder(season)}/{base}{ext}"


def series_extra_rel(title, year, season: int, ext: str, imdb=None, tmdb=None, tags=True, extra: str = "extras", extra_name: str = "") -> str:
    """Extras of a series (e.g. play-all or bonus material) in the series folder."""
    extra = extra if extra in EXTRA_DIRS else "extras"
    return f"{series_folder(title, year, imdb, tmdb, tags)}/{extra}/{clean_part(extra_name, 150) or 'Extra'}{ext}"


def unique_variant(rel: str, n: int) -> str:
    """Fallback name on a conflict: `… S01E03.mkv` -> `… S01E03 - 2.mkv` (never overwrite)."""
    stem, dot, ext = rel.rpartition(".")
    return f"{stem} - {n}.{ext}" if dot else f"{rel} - {n}"


# ---- backwards: reading names (for `GET /api/media/info`, also for files that were not sorted by this tool)
_TAIL = re.compile(r"^(?P<title>.*?)(?:\s*\((?P<year>(?:19|20)\d{2})\))?(?:\s*\[(?P<idk>tmdbid|imdbid|tvdbid)-(?P<idv>[^\]]+)\])?$")
_EPI = re.compile(r"[Ss](\d{1,2})[ ._-]?[Ee](\d{1,3})(?:[-–]?[Ee]?(\d{1,3}))?")


def split_name(name: str) -> dict:
    """`Title (2017) [imdbid-tt1856101]` -> {title, year, tag, id}."""
    m = _TAIL.match(name.strip())
    d = m.groupdict() if m else {}
    return {"title": (d.get("title") or name).strip(), "year": int(d["year"]) if d.get("year") else None, "tag": d.get("idk") or "", "id": d.get("idv") or ""}


def parse_path(rel: str) -> dict:
    """Read type, title, year, season and episode from a path in the Jellyfin layout. Empty result if nothing fits."""
    parts = [p for p in rel.split("/") if p]
    if not parts:
        return {}
    fname = parts[-1]
    stem = fname.rsplit(".", 1)[0]
    for i, p in enumerate(parts[:-1]):
        sm = re.fullmatch(r"Season (\d{1,2})", p)
        if sm and i > 0:
            info = split_name(parts[i - 1])
            em = _EPI.search(stem)
            out = {"kind": "series", **info, "season": int(sm.group(1))}
            if em:
                a, b = int(em.group(2)), int(em.group(3) or em.group(2))
                out.update(episode=a, episode_end=max(a, b))
            return out
    em = _EPI.search(stem)
    if em and len(parts) >= 1:
        title = re.sub(r"[._]", " ", stem[:em.start()]).strip(" -")
        a, b = int(em.group(2)), int(em.group(3) or em.group(2))
        info = split_name(title) if title else {"title": parts[-2] if len(parts) > 1 else "", "year": None, "tag": "", "id": ""}
        return {"kind": "series", **info, "season": int(em.group(1)), "episode": a, "episode_end": max(a, b)}
    if len(parts) >= 2:
        folder = split_name(parts[-2] if parts[-2].lower() not in EXTRA_DIRS or len(parts) < 3 else parts[-3])
        if folder["year"] and (stem.startswith(parts[-2]) or parts[-2].lower() in EXTRA_DIRS):
            return {"kind": "movie", **folder, "extra": parts[-2].lower() in EXTRA_DIRS}
    return {}
