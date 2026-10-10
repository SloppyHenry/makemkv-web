#!/usr/bin/env python3
"""Kleiner Attrappen-Server für die TMDB-API (nur Entwicklung/Tests, kein Netzwerkzugriff auf TMDB).

  python3 scripts/tmdb_mock.py 8841        dann die App mit MEDIA_TMDB_BASE=http://127.0.0.1:8841/3 starten
Gültiger Schlüssel: „testkey“ (alles andere -> 401). Die Daten stehen in FIXTURES und sind Beispiele, keine echten TMDB-Antworten.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

KEY = "testkey"
EP = [("Days Gone Bye", 67), ("Guts", 44), ("Tell It to the Frogs", 45), ("Vatos", 44), ("Wildfire", 44), ("TS-19", 66)]
MOVIES = {603: {"id": 603, "title": "Matrix", "original_title": "The Matrix", "release_date": "1999-03-30", "overview": "Ein Hacker entdeckt die wahre Natur seiner Welt.",
                "poster_path": "/matrix.jpg", "runtime": 136, "imdb_id": "tt0133093"},
          335984: {"id": 335984, "title": "Blade Runner 2049", "original_title": "Blade Runner 2049", "release_date": "2017-10-04",
                   "overview": "Ein junger Blade Runner stößt auf ein lange gehütetes Geheimnis.", "poster_path": "/br2049.jpg", "runtime": 164, "imdb_id": "tt1856101"},
          78: {"id": 78, "title": "Blade Runner", "original_title": "Blade Runner", "release_date": "1982-06-25", "overview": "Los Angeles 2019.", "poster_path": "/br.jpg",
               "runtime": 117, "imdb_id": "tt0083658"}}
SHOWS = {1402: {"id": 1402, "name": "The Walking Dead", "original_name": "The Walking Dead", "first_air_date": "2010-10-31",
                "overview": "Sheriff Rick Grimes erwacht aus dem Koma und findet eine Welt voller Untoter vor.", "poster_path": "/twd.jpg",
                "episode_run_time": [44], "seasons": [{"season_number": 0}, {"season_number": 1}, {"season_number": 2}], "external_ids": {"imdb_id": "tt1520211"}},
         94305: {"id": 94305, "name": "The Walking Dead: World Beyond", "original_name": "The Walking Dead: World Beyond", "first_air_date": "2020-10-04",
                 "overview": "Jugendliche in der Apokalypse.", "poster_path": "/twdwb.jpg", "episode_run_time": [45], "seasons": [{"season_number": 1}],
                 "external_ids": {"imdb_id": "tt10148174"}}}


def search(kind, q, year):
    pool = MOVIES if kind == "movie" else SHOWS
    out = []
    for r in pool.values():
        name = (r.get("title") or r.get("name")).lower()
        y = (r.get("release_date") or r.get("first_air_date"))[:4]
        if all(w in name for w in q.lower().split()) and (not year or y == year):
            out.append({k: v for k, v in r.items() if k not in ("runtime", "imdb_id", "external_ids", "seasons", "episode_run_time")})
    return {"results": out}


class H(BaseHTTPRequestHandler):
    def reply(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if q.get("api_key") != KEY and self.headers.get("Authorization") != f"Bearer {KEY}":
            return self.reply(401, {"status_message": "Invalid API key"})
        p = u.path.removeprefix("/3")
        if p == "/authentication":
            return self.reply(200, {"success": True})
        if p in ("/search/movie", "/search/tv"):
            return self.reply(200, search(p.split("/")[-1], q.get("query", ""), q.get("year") or q.get("first_air_date_year")))
        if p.startswith("/find/"):
            imdb = p.split("/")[-1]
            return self.reply(200, {"movie_results": [search("movie", m["title"], "")["results"][0] for m in MOVIES.values() if m["imdb_id"] == imdb],
                                    "tv_results": [{k: v for k, v in s.items() if k != "external_ids"} for s in SHOWS.values() if s["external_ids"]["imdb_id"] == imdb]})
        parts = p.strip("/").split("/")
        if parts[0] == "movie" and len(parts) == 2 and int(parts[1]) in MOVIES:
            return self.reply(200, MOVIES[int(parts[1])])
        if parts[0] == "tv" and len(parts) == 2 and int(parts[1]) in SHOWS:
            return self.reply(200, SHOWS[int(parts[1])])
        if parts[0] == "tv" and len(parts) == 4 and parts[2] == "season" and int(parts[1]) == 1402:
            n = int(parts[3])
            eps = [{"episode_number": i + 1, "name": e[0], "runtime": e[1], "air_date": "2010-11-01"} for i, e in enumerate(EP)] if n == 1 else []
            return self.reply(200 if eps else 404, {"episodes": eps})
        self.reply(404, {"status_message": "not found"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8841
    print(f"TMDB-Attrappe auf http://127.0.0.1:{port}/3 (Schlüssel: {KEY})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
