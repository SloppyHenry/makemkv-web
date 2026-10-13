"""Storage of the companion data under DATA/media/ (not in the NAS folder, so that Jellyfin does not trip over it).

- discs.json   disc info when ripping: {"discs": {id: {name, type, volume, titles}}, "files": {path: {disc, title}}}
- items.json   known media per file (after sorting): {path: {kind, title, year, tmdb, imdb, poster, season, episode …}}
- series.json  progress per series: {"tmdb:1402" | "title|year": {"seasons": {"1": {"next": 6, "discs": {"1": [1, 5]}}}}}
- history.json list of sort actions (newest last, at most 50) for "undo"
- cache.json   answers from TMDB
Paths are relative to the output folder as long as the file is there, otherwise absolute.
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
    """Tests only: forget the in-memory cache (the file is read again)."""
    with _lock:
        _mem.clear()


# ---- companion data when ripping
def disc_id(disc: dict) -> str:
    import hashlib
    raw = f"{disc.get('name')}|{disc.get('volume')}|" + ",".join(str(t.get("duration")) for t in disc.get("titles", []))
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def remember_rip(info: dict):
    """Rip hook: remember the disc name, label, all titles with runtimes and this title under its target path."""
    disc, title = info.get("disc") or {}, info.get("title") or {}
    if not disc or not info.get("rel"):
        return
    with _lock:
        d = load("discs.json", {"discs": {}, "files": {}})
        did = disc_id(disc)
        d["discs"][did] = {"name": disc.get("name", ""), "type": disc.get("type", ""), "volume": disc.get("volume", ""),
                           "titles": [{k: t.get(k) for k in ("id", "name", "duration", "bytes", "chapters")} for t in disc.get("titles", [])]}
        d["files"][info["rel"]] = {"disc": did, "title": {k: title.get(k) for k in ("id", "name", "duration", "bytes", "chapters")}}
        if len(d["files"]) > 5000:                                   # discard old entries
            for k in list(d["files"])[:500]:
                del d["files"][k]
        save("discs.json")


def rekey_file(old: str, new: str):
    """The transfer chose a different name (unique_path): move the entry."""
    with _lock:
        d = load("discs.json", {"discs": {}, "files": {}})
        if old != new and old in d["files"]:
            d["files"][new] = d["files"].pop(old)
            save("discs.json")


def sidecar(rel: str) -> dict | None:
    """{disc: {name, volume, titles}, title: {id, duration …}} or None."""
    d = load("discs.json", {"discs": {}, "files": {}})
    f = d["files"].get(rel)
    if not f or f["disc"] not in d["discs"]:
        return None
    return {"disc": d["discs"][f["disc"]], "title": f["title"]}


def move_keys(old: str, new: str):
    """Path changed (sorting, undo): companion data and media entries follow."""
    with _lock:
        for name, default in (("discs.json", {"discs": {}, "files": {}}), ("items.json", {})):
            data = load(name, default)
            tgt = data["files"] if name == "discs.json" else data
            if old in tgt:
                tgt[new] = tgt.pop(old)
                save(name)
