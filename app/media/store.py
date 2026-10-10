"""Ablage der Begleitdaten unter DATA/media/ (nicht im NAS-Ordner, damit Jellyfin nicht stolpert).

- discs.json   Disc-Infos beim Rippen: {"discs": {id: {name, type, volume, titles}}, "files": {pfad: {disc, title}}}
- items.json   bekannte Medien je Datei (nach dem Einsortieren): {pfad: {kind, title, year, tmdb, imdb, poster, season, episode …}}
- series.json  Fortschritt je Serie: {"tmdb:1402" | "titel|jahr": {"seasons": {"1": {"next": 6, "discs": {"1": [1, 5]}}}}}
- history.json Liste der Einsortier-Aktionen (neueste zuletzt, höchstens 50) für „Rückgängig“
- cache.json   Antworten von TMDB
Pfade sind relativ zum Ausgabeordner, solange die Datei dort liegt, sonst absolut.
"""
import json
import os
import threading
from pathlib import Path

from app.config import DATA

_lock = threading.RLock()
_mem: dict[str, object] = {}


def folder() -> Path:
    return DATA / "media"


def load(name: str, default):
    with _lock:
        if name in _mem:
            return _mem[name]
        try:
            val = json.loads((folder() / name).read_text())
        except (OSError, ValueError):
            val = default
        _mem[name] = val if isinstance(val, type(default)) else default
        return _mem[name]


def save(name: str):
    with _lock:
        folder().mkdir(parents=True, exist_ok=True)
        tmp = folder() / (name + ".tmp")
        tmp.write_text(json.dumps(_mem[name], ensure_ascii=False))
        os.replace(tmp, folder() / name)


def reset_memory():
    """Nur für Tests: Zwischenspeicher im Arbeitsspeicher vergessen (Datei wird neu gelesen)."""
    with _lock:
        _mem.clear()


# ---- Begleitdaten beim Rippen
def disc_id(disc: dict) -> str:
    import hashlib
    raw = f"{disc.get('name')}|{disc.get('volume')}|" + ",".join(str(t.get("duration")) for t in disc.get("titles", []))
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def remember_rip(info: dict):
    """Rip-Hook: Disc-Name, Label, alle Titel mit Laufzeiten und diesen Titel unter seinem Zielpfad merken."""
    disc, title = info.get("disc") or {}, info.get("title") or {}
    if not disc or not info.get("rel"):
        return
    with _lock:
        d = load("discs.json", {"discs": {}, "files": {}})
        did = disc_id(disc)
        d["discs"][did] = {"name": disc.get("name", ""), "type": disc.get("type", ""), "volume": disc.get("volume", ""),
                           "titles": [{k: t.get(k) for k in ("id", "name", "duration", "bytes", "chapters")} for t in disc.get("titles", [])]}
        d["files"][info["rel"]] = {"disc": did, "title": {k: title.get(k) for k in ("id", "name", "duration", "bytes", "chapters")}}
        if len(d["files"]) > 5000:                                   # alte Einträge verwerfen
            for k in list(d["files"])[:500]:
                del d["files"][k]
        save("discs.json")


def rekey_file(old: str, new: str):
    """Übertragung hat einen anderen Namen gewählt (unique_path): Eintrag umhängen."""
    with _lock:
        d = load("discs.json", {"discs": {}, "files": {}})
        if old != new and old in d["files"]:
            d["files"][new] = d["files"].pop(old)
            save("discs.json")


def sidecar(rel: str) -> dict | None:
    """{disc: {name, volume, titles}, title: {id, duration …}} oder None."""
    d = load("discs.json", {"discs": {}, "files": {}})
    f = d["files"].get(rel)
    if not f or f["disc"] not in d["discs"]:
        return None
    return {"disc": d["discs"][f["disc"]], "title": f["title"]}


def move_keys(old: str, new: str):
    """Pfad geändert (Einsortieren, Rückgängig): Begleitdaten und Medien-Einträge folgen."""
    with _lock:
        for name, default in (("discs.json", {"discs": {}, "files": {}}), ("items.json", {})):
            data = load(name, default)
            tgt = data["files"] if name == "discs.json" else data
            if old in tgt:
                tgt[new] = tgt.pop(old)
                save(name)
