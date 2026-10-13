"""Memory: which titles of a disc were ripped by hand? The next time the same disc is inserted (also on another
machine in the cluster) headless mode chooses the same titles with the same names and the same folder.

Keys are the disc ID and the content hash (discid.py); titles are found again like with TheDiscDB via runtime plus playlist or size.
File: DATA/headless-memory.json. Rips in headless mode itself are not remembered.
"""
import json
import time

from fastapi import HTTPException

from app.config import DATA
from app.headless import discdb
from app.state import peers_state

FILE = DATA / "headless-memory.json"
MAX_ENTRIES = 1000
NEW_RIP_AFTER = 6 * 3600          # titles of the same disc ripped later count as a new selection
_entries: list[dict] = []
_loaded = [False]


def _load():
    if _loaded[0]:
        return
    _loaded[0] = True
    try:
        v = json.loads(FILE.read_text())
        _entries[:] = [e for e in v.get("entries", []) if isinstance(e, dict)]
    except (OSError, ValueError):
        pass


def _save():
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        FILE.write_text(json.dumps({"entries": _entries[-MAX_ENTRIES:]}, ensure_ascii=False))
    except OSError as e:
        print("headless: memory not saved:", e, flush=True)


def find_local(disc_id: str, content_hash: str) -> dict | None:
    _load()
    for e in reversed(_entries):
        if disc_id and e.get("disc_id") == disc_id:
            return e
        if content_hash and e.get("content_hash") == content_hash and not (disc_id and e.get("disc_id")):
            return e
    return None


def count() -> int:
    _load()
    return len(_entries)


def record(ids: dict, disc: dict, title: dict, name: str, folder: str):
    """Remember a title ripped by hand (from the rip hook)."""
    if not (ids.get("disc_id") or ids.get("content_hash")):
        return
    e = find_local(ids.get("disc_id", ""), ids.get("content_hash", ""))
    now = time.time()
    if e is None:
        e = {"disc_id": ids.get("disc_id", ""), "content_hash": ids.get("content_hash", ""), "titles": []}
        _entries.append(e)
    elif now - e.get("t", 0) > NEW_RIP_AFTER:
        e["titles"] = []
    e.update(t=now, disc=disc.get("name") or disc.get("volume") or "", type=disc.get("type", ""), folder=folder)
    item = {"source_file": title.get("source", ""), "duration": title.get("duration_text", ""), "size": title.get("bytes", 0),
            "segment_map": title.get("segments", ""), "name": name}
    e["titles"] = [x for x in e["titles"] if not (x["source_file"] == item["source_file"] and x["size"] == item["size"])] + [item]
    _save()


def forget(disc_id: str, content_hash: str) -> bool:
    e = find_local(disc_id, content_hash)
    if e is None:
        return False
    _entries.remove(e)
    _save()
    return True


async def lookup(ids: dict) -> tuple[dict | None, str]:
    """First here, then on the other machines (capability headless_memory). Returns (entry, where it was found)."""
    did, ch = ids.get("disc_id", ""), ids.get("content_hash", "")
    if not (did or ch):
        return None, ""
    e = find_local(did, ch)
    if e:
        return e, "this machine"
    from app import cluster
    for name, p in list(peers_state.items()):
        if not (p.get("reachable") and (p.get("capabilities") or {}).get("headless_memory")):
            continue
        try:
            r = await cluster.peer_call(name, "headless/memory/lookup", {"disc_id": did, "content_hash": ch}, timeout=6)
        except HTTPException:
            continue
        if isinstance(r, dict) and isinstance(r.get("entry"), dict):
            return r["entry"], name
    return None, ""


def match(entry: dict, disc: dict) -> dict:
    """Find the remembered titles on the current disc again. {ok, picks, names, folder, reason}."""
    bluray = "blu" in (disc.get("type") or entry.get("type") or "").lower()
    res = {"ok": False, "picks": [], "names": {}, "folder": entry.get("folder") or "", "reason": ""}
    used: set[int] = set()
    for it in entry.get("titles") or []:
        c = [i for i in discdb.candidates(it, disc["titles"], bluray) if i not in used]
        if len(c) != 1:
            res["reason"] = f"remembered title \"{it.get('name')}\" " + ("not found" if not c else "not unambiguous")
            return res
        used.add(c[0])
        res["picks"].append(c[0])
        res["names"][c[0]] = it.get("name") or ""
    res["ok"] = bool(res["picks"])
    if not res["ok"]:
        res["reason"] = "the remembered selection is empty"
    return res
