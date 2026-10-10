"""Benennung nach dem Jellyfin-Schema (reine Funktionen, ohne Dateizugriff).

Regeln nach der Jellyfin-Dokumentation (Stand 2026-10, https://jellyfin.org/docs/general/server/media/movies/ und .../shows/):
- Film: `Titel (Jahr) [imdbid-tt…]/Titel (Jahr) [imdbid-tt…].mkv`; weitere Fassungen mit Trenner und Name dahinter (`… - 1080p.mkv`);
  Extras in Unterordnern (extras, behind the scenes, deleted scenes, featurettes, interviews, scenes, shorts, trailers …).
- Serie: `Serie (Jahr) [tmdbid-…]/Season 01/Serie S01E01.mkv`; Doppelfolgen `S01E01-E02`; Episodenname darf dahinter stehen;
  Specials in `Season 00`; „Season“ nie abkürzen, Zahl mit führender Null.
- Unzulässig in Namen: < > : " / \\ | ? *  (hier ersetzt bzw. entfernt), kein Punkt oder Leerzeichen am Ende.
"""
import re
import unicodedata

EXTRA_DIRS = ("extras", "behind the scenes", "deleted scenes", "featurettes", "interviews", "scenes", "shorts", "trailers", "samples", "clips", "other")
VIDEO_EXT = (".mkv", ".mp4", ".m4v", ".avi", ".m2ts", ".iso")


def clean_part(s: str, maxlen: int = 120) -> str:
    """Einen Namensbestandteil dateisystemtauglich machen (Umlaute bleiben)."""
    s = unicodedata.normalize("NFC", s or "")
    s = re.sub(r"[\x00-\x1f]", "", s)
    s = re.sub(r"\s*:\s*", " - ", s)                 # „Star Trek: Voyager“ -> „Star Trek - Voyager“
    s = s.replace('"', "'")
    s = re.sub(r"[?*<>]", "", s)
    s = re.sub(r"\s*[/\\|]\s*", " - ", s)
    s = re.sub(r"(?:\s-\s){2,}", " - ", s)
    s = re.sub(r"\s+", " ", s).strip(" .-")
    return s[:maxlen].rstrip(" .-")


def id_tag(imdb: str | None = None, tmdb: int | str | None = None, prefer: str = "imdb") -> str:
    """`[imdbid-tt0133093]` oder `[tmdbid-603]`; leer, wenn keine ID bekannt ist."""
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
    """`Titel (Jahr) [imdbid-tt…]` – Jahr und ID nur, wenn bekannt (und die ID nur bei `tags`)."""
    name = clean_part(title) or "Unbenannt"
    if str(year or "").isdigit():
        name += f" ({int(year)})"
    tag = id_tag(imdb, tmdb, prefer) if tags else ""
    return f"{name} {tag}" if tag else name


def movie_rel(title, year, ext, imdb=None, tmdb=None, tags=True, version: str = "", extra: str = "", extra_name: str = "") -> str:
    """Relativer Pfad eines Films unterhalb des Filme-Ordners.
    `version` (z. B. „1080p“, „Director's Cut“) hängt die Fassung an; `extra` (Name aus EXTRA_DIRS) legt die Datei in einen Extras-Unterordner."""
    folder = media_name(title, year, imdb, tmdb, tags, "imdb")
    if extra:
        extra = extra if extra in EXTRA_DIRS else "extras"
        return f"{folder}/{extra}/{clean_part(extra_name, 150) or 'Extra'}{ext}"
    ver = f" - {clean_part(version, 40)}" if clean_part(version, 40) else ""
    return f"{folder}/{folder}{ver}{ext}"


def season_folder(season: int) -> str:
    return f"Season {int(season):02d}"


def episode_code(season: int, episodes: list[int]) -> str:
    """`S01E01` bzw. `S01E01-E02` für Doppelfolgen (fortlaufend)."""
    eps = sorted(set(int(e) for e in episodes))
    if not eps or eps[0] < 0:
        raise ValueError("keine Episode")
    if eps != list(range(eps[0], eps[-1] + 1)):
        raise ValueError("Episoden einer Datei müssen fortlaufend sein")
    code = f"S{int(season):02d}E{eps[0]:02d}"
    return code + (f"-E{eps[-1]:02d}" if len(eps) > 1 else "")


def series_folder(title, year=None, imdb=None, tmdb=None, tags=True) -> str:
    return media_name(title, year, imdb, tmdb, tags, "tmdb")


def episode_rel(title, year, season: int, episodes: list[int], ext: str, imdb=None, tmdb=None, tags=True, ep_name: str = "") -> str:
    """Relativer Pfad einer Episode unterhalb des Serien-Ordners: `Serie (Jahr) [tmdbid-…]/Season 01/Serie S01E01 - Name.mkv`."""
    base = f"{clean_part(title) or 'Unbenannt'} {episode_code(season, episodes)}"
    name = clean_part(ep_name, 100)
    if name:
        base += f" - {name}"
    return f"{series_folder(title, year, imdb, tmdb, tags)}/{season_folder(season)}/{base}{ext}"


def series_extra_rel(title, year, season: int, ext: str, imdb=None, tmdb=None, tags=True, extra: str = "extras", extra_name: str = "") -> str:
    """Extras einer Serie (z. B. Play-All oder Bonusmaterial) im Serienordner."""
    extra = extra if extra in EXTRA_DIRS else "extras"
    return f"{series_folder(title, year, imdb, tmdb, tags)}/{extra}/{clean_part(extra_name, 150) or 'Extra'}{ext}"


def unique_variant(rel: str, n: int) -> str:
    """Ausweichname bei Konflikt: `… S01E03.mkv` -> `… S01E03 - 2.mkv` (niemals überschreiben)."""
    stem, dot, ext = rel.rpartition(".")
    return f"{stem} - {n}.{ext}" if dot else f"{rel} - {n}"


# ---- Rückwärts: Namen lesen (für `GET /api/media/info`, auch bei Dateien, die nicht über dieses Tool einsortiert wurden)
_TAIL = re.compile(r"^(?P<title>.*?)(?:\s*\((?P<year>(?:19|20)\d{2})\))?(?:\s*\[(?P<idk>tmdbid|imdbid|tvdbid)-(?P<idv>[^\]]+)\])?$")
_EPI = re.compile(r"[Ss](\d{1,2})[ ._-]?[Ee](\d{1,3})(?:[-–]?[Ee]?(\d{1,3}))?")


def split_name(name: str) -> dict:
    """`Titel (2017) [imdbid-tt1856101]` -> {title, year, tag, id}."""
    m = _TAIL.match(name.strip())
    d = m.groupdict() if m else {}
    return {"title": (d.get("title") or name).strip(), "year": int(d["year"]) if d.get("year") else None, "tag": d.get("idk") or "", "id": d.get("idv") or ""}


def parse_path(rel: str) -> dict:
    """Aus einem Pfad im Jellyfin-Aufbau Art, Titel, Jahr, Staffel und Episode lesen. Leeres Ergebnis, wenn nichts passt."""
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
