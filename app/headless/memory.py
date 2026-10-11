"""Gedächtnis: Welche Titel wurden bei einer Disc von Hand gerippt? Beim nächsten Einlegen derselben Disc (auch an einem anderen
Rechner im Verbund) wählt der Headless-Modus dieselben Titel mit denselben Namen und demselben Ordner.

Schlüssel sind Disc-ID und Inhalts-Hash (discid.py); Titel werden wie bei TheDiscDB über Laufzeit plus Playlist bzw. Größe
wiedergefunden. Datei: DATA/headless-memory.json. Rips im Headless-Modus selbst werden nicht gemerkt.
"""
import json
import time

from fastapi import HTTPException

from app.config import DATA
from app.headless import discdb
from app.state import peers_state

FILE = DATA / "headless-memory.json"
MAX_ENTRIES = 1000
NEW_RIP_AFTER = 6 * 3600          # später gerippte Titel derselben Disc gelten als neue Auswahl
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
        print("headless: Gedächtnis nicht gespeichert:", e, flush=True)


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
    """Einen von Hand gerippten Titel merken (aus dem Rip-Hook)."""
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
    """Erst hier, dann bei den anderen Rechnern (Fähigkeit headless_memory). Rückgabe (Eintrag, wo gefunden)."""
    did, ch = ids.get("disc_id", ""), ids.get("content_hash", "")
    if not (did or ch):
        return None, ""
    e = find_local(did, ch)
    if e:
        return e, "dieser Rechner"
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
    """Gemerkte Titel in der aktuellen Disc wiederfinden. {ok, picks, names, folder, reason}."""
    bluray = "blu" in (disc.get("type") or entry.get("type") or "").lower()
    res = {"ok": False, "picks": [], "names": {}, "folder": entry.get("folder") or "", "reason": ""}
    used: set[int] = set()
    for it in entry.get("titles") or []:
        c = [i for i in discdb.candidates(it, disc["titles"], bluray) if i not in used]
        if len(c) != 1:
            res["reason"] = f"gemerkter Titel „{it.get('name')}“ " + ("nicht gefunden" if not c else "nicht eindeutig")
            return res
        used.add(c[0])
        res["picks"].append(c[0])
        res["names"][c[0]] = it.get("name") or ""
    res["ok"] = bool(res["picks"])
    if not res["ok"]:
        res["reason"] = "gemerkte Auswahl ist leer"
    return res
