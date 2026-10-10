"""Was weiß das Tool über eine Datei? Für `GET /api/media/info` (Gruppierung in der Bibliothek, PF)."""
from app.media import metadata, naming, store


def info_for(rel: str) -> dict:
    """{path, known, source: tool|name, kind, title, year, tmdb, imdb, poster, season, episode, episode_end, episode_name}.
    `tool`: über den Assistenten einsortiert (mit Poster); `name`: aus einem Pfad im Jellyfin-Aufbau gelesen; sonst known=false."""
    rec = store.load("items.json", {}).get(rel)
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
