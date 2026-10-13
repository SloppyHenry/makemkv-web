"""What does the tool know about a file? For `GET /api/media/info` (grouping in the library, PF)."""
from pathlib import Path

from app.media import metadata, naming, store


def info_for(rel: str) -> dict:
    """{path, known, source: tool|name, kind, title, year, tmdb, imdb, poster, season, episode, episode_end, episode_name}.
    `tool`: sorted via the wizard (with poster); `name`: read from a path in the Jellyfin layout; otherwise known=false."""
    key = str(Path(rel).resolve()) if rel.startswith("/") else rel
    rec = store.load("items.json", {}).get(key)
    if rec:
        eps = rec.get("episodes") or []
        return {"path": rel, "known": True, "source": "tool", "kind": rec.get("kind"), "title": rec.get("title"), "year": rec.get("year"),
                "tmdb": rec.get("tmdb"), "imdb": rec.get("imdb"), "poster": metadata.poster_url(rec.get("poster")), "season": rec.get("season"),
                "episode": min(eps) if eps else None, "episode_end": max(eps) if eps else None, "episode_name": rec.get("name") or "", "role": rec.get("role")}
    g = naming.parse_path(rel)
    if g:
        return {"path": rel, "known": True, "source": "name", "kind": g["kind"], "title": g["title"], "year": g["year"],
                "tmdb": int(g["id"]) if g["tag"] == "tmdbid" and g["id"].isdigit() else None, "imdb": g["id"] if g["tag"] == "imdbid" else None,
                "poster": "", "season": g.get("season"), "episode": g.get("episode"), "episode_end": g.get("episode_end"), "episode_name": "",
                "role": "extra" if g.get("extra") else None}
    return {"path": rel, "known": False}
