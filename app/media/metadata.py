"""TMDB client (search, resolve IMDb IDs, details, seasons) with a cache.

The user provides the API key (Settings → Media / Jellyfin). Without a key there are no requests; the interface then asks for
title and year by hand. Allowed are the v3 key (32 characters, as a parameter) and the v4 "read access token" (starts with "eyJ", as a bearer).
`MEDIA_TMDB_BASE` overrides the address (tests against scripts/tmdb_mock.py).
"""
import asyncio
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from app.media import store

BASE = os.environ.get("MEDIA_TMDB_BASE", "https://api.themoviedb.org/3").rstrip("/")
IMG = os.environ.get("MEDIA_TMDB_IMG", "https://image.tmdb.org/t/p").rstrip("/")
TTL_SEARCH, TTL_DETAIL = 7 * 86400, 30 * 86400
MAX_CACHE = 2000


class MetadataError(Exception):
    """Error with a readable message; `code`: no_key | bad_key | not_found | network | rate."""

    def __init__(self, msg: str, code: str = "network"):
        super().__init__(msg)
        self.code = code


def poster_url(path: str | None, size: str = "w342") -> str:
    return f"{IMG}/{size}{path}" if path else ""


def _http_get(url: str, headers: dict, timeout: float = 10) -> tuple[int, bytes]:
    """The only place with network access (tests replace it)."""
    req = urllib.request.Request(url, headers={"User-Agent": "spindle", "Accept": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        with e:
            return e.code, e.read()


def _auth(key: str) -> tuple[dict, dict]:
    key = (key or "").strip()
    if key.startswith("eyJ") and len(key) > 60:
        return {}, {"Authorization": f"Bearer {key}"}
    return {"api_key": key}, {}


def _cache():
    return store.load("cache.json", {})


async def _get(key: str, path: str, params: dict | None = None, ttl: float = TTL_DETAIL, fresh: bool = False) -> dict:
    if not (key or "").strip():
        raise MetadataError("No TMDB key set.", "no_key")
    params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    ck = path + "?" + urllib.parse.urlencode(sorted(params.items()))
    c = _cache()
    hit = c.get(ck)
    if hit and not fresh and time.time() - hit["t"] < ttl:
        return hit["v"]
    q, headers = _auth(key)
    url = f"{BASE}{path}?{urllib.parse.urlencode({**params, **q})}"
    try:
        status, body = await asyncio.to_thread(_http_get, url, headers)
    except (OSError, ValueError) as e:
        if hit:                                                      # old data is better than none
            return hit["v"]
        raise MetadataError(f"TMDB not reachable: {e}", "network")
    if status in (401, 403):
        raise MetadataError("TMDB refuses the key (invalid or blocked).", "bad_key")
    if status == 404:
        raise MetadataError("Not found on TMDB.", "not_found")
    if status == 429:
        raise MetadataError("TMDB request limit reached, please wait a moment.", "rate")
    if status != 200:
        raise MetadataError(f"TMDB error {status}.", "network")
    try:
        val = json.loads(body)
    except ValueError:
        raise MetadataError("Invalid answer from TMDB.", "network")
    c[ck] = {"t": time.time(), "v": val}
    if len(c) > MAX_CACHE:
        for k in sorted(c, key=lambda k: c[k]["t"])[:MAX_CACHE // 10]:
            del c[k]
    store.save("cache.json")
    return val


def clear_cache():
    _cache().clear()
    store.save("cache.json")


def cache_size() -> int:
    return len(_cache())


def _year(date: str | None) -> int | None:
    return int(date[:4]) if date and re.match(r"\d{4}", date) else None


def _hit(kind: str, r: dict) -> dict:
    return {"kind": kind, "tmdb": r["id"], "title": r.get("title") or r.get("name") or "", "original": r.get("original_title") or r.get("original_name") or "",
            "year": _year(r.get("release_date") or r.get("first_air_date")), "overview": (r.get("overview") or "")[:300],
            "poster": r.get("poster_path") or "", "poster_url": poster_url(r.get("poster_path"), "w185")}


async def test_key(key: str) -> dict:
    """Check the key (GET /authentication). {ok, message}."""
    try:
        v = await _get(key, "/authentication", fresh=True)
        return {"ok": bool(v.get("success", True)), "message": "Connection ok"}
    except MetadataError as e:
        return {"ok": False, "message": str(e), "code": e.code}


async def search(key: str, kind: str, query: str, year: int | None = None, lang: str = "en-US") -> list[dict]:
    """kind: movie | tv. Results with title, year, short description and poster (at most 10)."""
    ytype = "year" if kind == "movie" else "first_air_date_year"
    v = await _get(key, f"/search/{kind}", {"query": query.strip(), ytype: year or "", "language": lang, "include_adult": "false"}, TTL_SEARCH)
    return [_hit(kind, r) for r in v.get("results", [])[:10]]


async def details(key: str, kind: str, tmdb: int, lang: str = "en-US") -> dict:
    """Movie or series including the IMDb ID (from external_ids), runtime and number of seasons."""
    v = await _get(key, f"/{kind}/{int(tmdb)}", {"language": lang, "append_to_response": "external_ids"})
    ids = v.get("external_ids") or {}
    runtime = v.get("runtime") or (v.get("episode_run_time") or [None])[0]
    return {**_hit(kind, v), "imdb": v.get("imdb_id") or ids.get("imdb_id") or "", "runtime": runtime,
            "seasons": [s["season_number"] for s in v.get("seasons", [])] if kind == "tv" else [],
            "status": v.get("status", "")}


async def find_imdb(key: str, imdb: str, lang: str = "en-US") -> dict | None:
    """Resolve an IMDb ID (tt…) via TMDB /find -> a result like `search` or None."""
    imdb = imdb.strip()
    if not re.fullmatch(r"tt\d{6,10}", imdb):
        raise MetadataError("That is not a valid IMDb ID (example: tt1520211).", "not_found")
    v = await _get(key, f"/find/{imdb}", {"external_source": "imdb_id", "language": lang}, TTL_DETAIL)
    for kind, field in (("movie", "movie_results"), ("tv", "tv_results")):
        if v.get(field):
            return {**_hit(kind, v[field][0]), "imdb": imdb}
    return None


async def season(key: str, tmdb: int, number: int, lang: str = "en-US") -> list[dict]:
    """Episodes of a season: [{n, name, runtime, air}]."""
    v = await _get(key, f"/tv/{int(tmdb)}/season/{int(number)}", {"language": lang})
    return [{"n": e["episode_number"], "name": e.get("name") or "", "runtime": e.get("runtime"), "air": e.get("air_date") or ""} for e in v.get("episodes", [])]
