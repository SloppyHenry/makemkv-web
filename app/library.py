"""Bibliothek: Dateien im Ziel erkennen, nachträglich konvertieren, umbenennen."""
import asyncio
import json
import os
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app import ext
from app.convert import clean_convert, next_conversion_id
from app.ffmpeg import probe
from app.config import INSTANCE, LIBCACHE, LIB_CODECS, LIB_EXT, LOCK_TTL
from app.files import acquire_lock, busy_reason, fresh_lock_in, held_locks, inside_out, lock_path, out_dir
from app.state import ACTIVE, CV_ACTIVE, broadcast, convert_queue, conversions, out_cache, peers_state, uploads
from app.util import valid_name


router = APIRouter()
ext.allow_proxy(r"library/convert")


lib_cache: dict[str, dict] = {}
lib_probe_queue: asyncio.Queue = asyncio.Queue()
lib_probing: set[str] = set()


def lib_info(pr: dict) -> dict:
    v = next((x for x in pr["streams"] if x["codec_type"] == "video"), {})
    auds = [x for x in pr["streams"] if x["codec_type"] == "audio"]
    return {"codec": v.get("codec_name", ""), "w": v.get("width", 0), "h": v.get("height", 0), "pix": v.get("pix_fmt", ""),
            "hdr": v.get("color_transfer") in ("smpte2084", "arib-std-b67"),
            "dur": float(pr["format"].get("duration") or 0),
            "audio": [f'{a.get("codec_name", "?")} {a.get("channels", "?")}ch {a.get("tags", {}).get("language", "")}'.strip() for a in auds],
            "subs": sum(1 for x in pr["streams"] if x["codec_type"] == "subtitle")}


def lib_state(info) -> str:
    if info is None:
        return "unknown"
    if info["hdr"]:
        return "hdr"
    if info["codec"] == "hevc":
        return "hevc"
    return "ok" if info["codec"] in LIB_CODECS else "other"


def load_cache():
    try:
        lib_cache.update(json.loads(LIBCACHE.read_text()))
    except (OSError, ValueError):
        pass


def save_libcache():
    try:
        LIBCACHE.write_text(json.dumps(lib_cache))
    except OSError:
        pass


async def lib_probe_worker():
    n = 0
    while True:
        rel = await lib_probe_queue.get()
        try:
            p = Path(out_cache["dir"]) / rel
            st = p.stat()
            try:
                lib_cache[rel] = {"size": st.st_size, "mtime": st.st_mtime, "info": lib_info(await probe(p))}
            except Exception as e:  # noqa: BLE001
                lib_cache[rel] = {"size": st.st_size, "mtime": st.st_mtime, "info": None, "err": str(e)[:120]}
            n += 1
            if n % 10 == 0 or lib_probe_queue.empty():
                save_libcache()
        except OSError:
            pass
        finally:
            lib_probing.discard(rel)


def scan_library():
    base, _ = out_dir()
    items, locks = [], {}
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        if len(Path(root).relative_to(base).parts) >= 4:
            dirs[:] = []
        for f in files:
            full = Path(root) / f
            if f.startswith(".") and f.endswith(".mkw-lock"):
                try:
                    locks[str((Path(root) / f[1:-len(".mkw-lock")]).relative_to(base))] = (full.stat().st_mtime, full)
                except OSError:
                    pass
                continue
            if f.startswith(".") or not f.lower().endswith(LIB_EXT):
                continue
            try:
                st = full.stat()
            except OSError:
                continue
            items.append({"path": str(full.relative_to(base)), "size": st.st_size, "mtime": st.st_mtime})
    return str(base), items, locks


class LibReq(BaseModel):
    paths: list[str] = []
    convert: dict = {}
    takeover_from: str = ""          # Übergabe: Name der Instanz, die die Sperre gerade hält und abgibt


@router.get("/api/library")
async def api_library():
    base, items, locks = await asyncio.to_thread(scan_library)
    active = {c["rel"]: c for c in conversions if c.get("origin") == "library" and c["status"] in CV_ACTIVE}
    remote = {c["name"]: (pn, c) for pn, pe in peers_state.items() if pe.get("reachable") for c in pe.get("conversions", [])
              if c.get("origin") == "library" and c.get("status") in CV_ACTIVE}
    done = {u["name"] for u in uploads if u.get("replace") and u["status"] in ACTIVE}
    out = []
    for it in items:
        rel = it["path"]
        c = lib_cache.get(rel)
        fresh = c and c["size"] == it["size"] and c["mtime"] == it["mtime"]
        if fresh:
            info, state = c["info"], lib_state(c["info"])
        else:
            info, state = None, "probing" if rel.lower().endswith(".mkv") else "other"
            if rel.lower().endswith(".mkv") and rel not in lib_probing:
                lib_probing.add(rel)
                lib_probe_queue.put_nowait(rel)
        job = None
        if rel in active:
            job = {"status": active[rel]["status"], "pct": active[rel]["pct"], "id": active[rel]["id"]}
        elif rel in remote:
            job = {"status": remote[rel][1]["status"], "pct": remote[rel][1].get("pct", 0), "host": remote[rel][0], "id": remote[rel][1].get("id")}
        elif rel in done:
            job = {"status": "replacing", "pct": 1.0}
        lk = locks.get(rel)
        locked = None
        if lk and str(lk[1]) not in held_locks and time.time() - lk[0] < LOCK_TTL:
            try:
                locked = json.loads(lk[1].read_text()).get("inst", "andere Instanz")
            except (OSError, ValueError):
                locked = "andere Instanz"
        out.append({**it, "state": state, "info": info, "job": job, "locked": locked,
                    "dev_err": (c or {}).get("err", "") if not fresh or not c.get("info") else ""})
    out.sort(key=lambda x: -x["mtime"])
    return {"dir": base, "files": out[:1500], "probing": len(lib_probing), "instance": INSTANCE}


@router.post("/api/library/convert")
async def api_library_convert(req: LibReq):
    cfg = clean_convert({**req.convert, "convert": True})
    base, _ = out_dir()
    started, skipped = [], []
    for rel in req.paths[:300]:
        p = inside_out(rel)
        if not p.is_file():
            skipped.append({"path": rel, "why": "nicht gefunden"})
            continue
        if any(c.get("origin") == "library" and c["rel"] == rel and c["status"] in CV_ACTIVE for c in conversions):
            skipped.append({"path": rel, "why": "bereits in der Warteschlange"})
            continue
        st = p.stat()
        c = lib_cache.get(rel)
        if c and c["size"] == st.st_size and c["mtime"] == st.st_mtime and c["info"]:
            info = c["info"]
        else:
            try:
                info = lib_info(await probe(p))
            except Exception as e:  # noqa: BLE001
                skipped.append({"path": rel, "why": f"nicht lesbar: {str(e)[:80]}"})
                continue
            lib_cache[rel] = {"size": st.st_size, "mtime": st.st_mtime, "info": info}
        state = lib_state(info)
        if state != "ok":
            skipped.append({"path": rel, "why": {"hevc": "ist bereits HEVC", "hdr": "HDR – wird nicht umkodiert"}.get(state, "Codec wird nicht unterstützt")})
            continue
        owner = acquire_lock(p, req.takeover_from)
        if owner:
            skipped.append({"path": rel, "why": f"wird gerade von „{owner}“ bearbeitet"})
            continue
        conversions.append({"id": next_conversion_id(), "name": rel, "folder": str(Path(rel).parent), "src": str(p), "size_in": st.st_size, "size_out": 0,
                            "status": "queued", "pct": 0.0, "fps": 0.0, "speed": 0.0, "eta": 0, "error": "", "cfg": cfg, "dev": "",
                            "t": time.time(), "started": 0, "mode": "", "origin": "library", "rel": rel, "lock": str(lock_path(p)), "paused": False, "handed": "", "cancel": False})
        convert_queue.put_nowait(conversions[-1])
        started.append(rel)
    save_libcache()
    broadcast()
    return {"started": started, "skipped": skipped}


class RenameReq(BaseModel):
    path: str
    name: str


def move_cache(old: str, new: str):
    for k in [k for k in lib_cache if k == old or k.startswith(old + "/")]:
        lib_cache[new + k[len(old):]] = lib_cache.pop(k)
    save_libcache()


@router.post("/api/library/rename")
async def api_lib_rename(req: RenameReq):
    src = inside_out(req.path)
    if not src.is_file():
        raise HTTPException(404, "Datei nicht gefunden")
    name = valid_name(req.name)
    if Path(name).suffix.lower() != src.suffix.lower():
        name += src.suffix                                   # Endung bleibt erhalten
    dst = src.with_name(name)
    base = Path(out_cache["dir"]).resolve()
    rel_old, rel_new = str(src.relative_to(base)), str(dst.relative_to(base))
    if dst == src:
        return {"ok": True, "path": rel_old}
    if why := busy_reason(rel_old, False, src):
        raise HTTPException(409, f"Die Datei {why} und kann jetzt nicht umbenannt werden.")
    if fresh_lock_in(src, False):
        raise HTTPException(409, "Die Datei ist von einer anderen Instanz gesperrt.")
    if dst.exists():
        raise HTTPException(409, f"„{name}“ gibt es in diesem Ordner schon.")
    try:
        os.rename(src, dst)
    except PermissionError:
        raise HTTPException(403, "Keine Berechtigung zum Umbenennen (Ordner gehört auf dem NAS einem anderen Benutzer).")
    except OSError as e:
        raise HTTPException(500, f"Umbenennen fehlgeschlagen: {e}")
    move_cache(rel_old, rel_new)
    broadcast()
    return {"ok": True, "path": rel_new}


@router.post("/api/library/rename-folder")
async def api_lib_rename_folder(req: RenameReq):
    src = inside_out(req.path)
    base = Path(out_cache["dir"]).resolve()
    if not src.is_dir() or src == base:
        raise HTTPException(404, "Ordner nicht gefunden")
    name = valid_name(req.name)
    dst = src.with_name(name)
    rel_old, rel_new = str(src.relative_to(base)), str(dst.relative_to(base))
    if dst == src:
        return {"ok": True, "path": rel_old}
    if why := busy_reason(rel_old, True, src):
        raise HTTPException(409, f"Im Ordner {why}; er kann jetzt nicht umbenannt werden.")
    if fresh_lock_in(src, True):
        raise HTTPException(409, "Im Ordner ist eine Datei von einer anderen Instanz gesperrt.")
    if dst.exists():
        raise HTTPException(409, f"„{name}“ gibt es hier schon.")
    try:
        os.rename(src, dst)
    except PermissionError:
        raise HTTPException(403, "Keine Berechtigung zum Umbenennen (gehört auf dem NAS einem anderen Benutzer).")
    except OSError as e:
        raise HTTPException(500, f"Umbenennen fehlgeschlagen: {e}")
    move_cache(rel_old, rel_new)
    broadcast()
    return {"ok": True, "path": rel_new}
