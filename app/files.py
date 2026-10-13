"""Output target (NAS/fallback), path checks, lock files and the file API."""
import asyncio
import json
import os
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.config import INSTANCE, LOCK_TTL, OUT_FALLBACK, OUT_MOUNT, OUT_PREFERRED
from app.state import ACTIVE, CV_ACTIVE, conversions, drives, out_cache, uploads
from app.util import open_perms


router = APIRouter()


def mount_ok() -> bool:
    """True if OUT_MOUNT is a real NFS/CIFS mount (autofs gets triggered by this)."""
    try:
        os.listdir(OUT_MOUNT)
        with open("/proc/self/mountinfo") as f:
            for line in f:
                p = line.split()
                if p[4] == OUT_MOUNT:
                    fstype = p[p.index("-") + 1]
                    if fstype.startswith(("nfs", "cifs", "fuse")):
                        return True
    except OSError:
        pass
    return False


def out_dir() -> tuple[Path, bool]:
    if mount_ok():
        try:
            OUT_PREFERRED.mkdir(parents=True, exist_ok=True)
            if os.access(OUT_PREFERRED, os.W_OK):
                return OUT_PREFERRED, True
        except OSError:
            pass
    OUT_FALLBACK.mkdir(parents=True, exist_ok=True)
    return OUT_FALLBACK, False


held_locks: set[str] = set()


def lock_path(p: Path) -> Path:
    return p.with_name("." + p.name + ".mkw-lock")


def acquire_lock(p: Path, takeover_from: str = "") -> str:
    """Create a lock file next to the file (so that two instances do not rework the same file). Returns: '' = locked, otherwise the owner's name."""
    lp = lock_path(p)
    for _ in range(2):
        try:
            fd = os.open(lp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
        except FileExistsError:
            try:
                if time.time() - lp.stat().st_mtime > LOCK_TTL:      # orphaned -> take it over
                    lp.unlink(missing_ok=True)
                    continue
                owner = json.loads(lp.read_text()).get("inst", "another instance")
                if takeover_from and owner.lower() == takeover_from.lower():      # hand-over: the previous owner gives it up
                    lp.unlink(missing_ok=True)
                    continue
            except (OSError, ValueError):
                owner = "another instance"
            return owner
        with os.fdopen(fd, "w") as f:
            json.dump({"inst": INSTANCE, "t": time.time()}, f)
        open_perms(lp, False)
        held_locks.add(str(lp))
        return ""
    return "another instance"


def release_lock(lp: str):
    if not lp:                       # the lock was given up during a hand-over
        return
    held_locks.discard(lp)
    try:
        Path(lp).unlink(missing_ok=True)
    except OSError:
        pass


async def lock_heartbeat():
    while True:
        await asyncio.sleep(60)
        for lp in list(held_locks):
            try:
                os.utime(lp)
            except OSError:
                pass


def _probe_output():
    d, mounted = out_dir()
    return {"dir": str(d), "mounted": mounted, "free": shutil.disk_usage(d).free, "stalled": False}


async def output_refresher():
    """Check the output target in the background – a hanging network drive must not block the interface."""
    while True:
        try:
            out_cache.update(await asyncio.wait_for(asyncio.to_thread(_probe_output), 8))
        except asyncio.TimeoutError:
            out_cache["stalled"] = True
        except OSError:
            out_cache["stalled"] = True
        await asyncio.sleep(5)


def inside_out(rel: str) -> Path:
    base, _ = out_dir()
    p = (base / rel).resolve()
    if p != base.resolve() and base.resolve() not in p.parents:
        raise HTTPException(400, "Invalid path")
    return p


def busy_reason(rel: str, is_dir: bool, abs_path: Path) -> str:
    """Why something must not be renamed right now ('' = it may)."""
    hit = (lambda r: r.startswith(rel + "/")) if is_dir else (lambda r: r == rel)
    if any(c.get("origin") == "library" and c["status"] in CV_ACTIVE and hit(c["rel"]) for c in conversions):
        return "is being converted"
    if any(u["status"] in ACTIVE and (hit(u["name"]) or (is_dir and u["name"].startswith(rel + "/"))) for u in uploads):
        return "is being transferred"
    if is_dir and any(d.job and str(d.job.get("dest", "")).startswith(str(abs_path)) for d in drives.values()):
        return "is being written by a rip"
    return ""


def fresh_lock_in(p: Path, is_dir: bool) -> bool:
    paths = [p] if not is_dir else [f for f in p.rglob("*") if f.is_file() and f.name.endswith(".mkw-lock")]
    for f in paths:
        lp = f if is_dir else lock_path(p)
        try:
            if time.time() - lp.stat().st_mtime < LOCK_TTL and str(lp) not in held_locks:
                return True
        except OSError:
            continue
    return False


@router.get("/api/files")
def api_files():
    base, _ = out_dir()
    items = []
    for root, dirs, files in os.walk(base):
        depth = Path(root).relative_to(base).parts
        if len(depth) >= 3:
            dirs[:] = []
        for f in files:
            if f.lower().endswith((".mkv", ".iso", ".m2ts")):
                p = Path(root) / f
                try:
                    st = p.stat()
                except OSError:
                    continue
                items.append({"path": str(p.relative_to(base)), "size": st.st_size, "mtime": st.st_mtime})
    items.sort(key=lambda x: -x["mtime"])
    return {"dir": str(base), "files": items[:200]}


@router.get("/api/download")
def api_download(path: str):
    p = inside_out(path)
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, filename=p.name)


@router.delete("/api/files")
def api_delete(path: str):
    p = inside_out(path)
    if not p.is_file():
        raise HTTPException(404)
    lp = lock_path(p)
    if lp.exists() and time.time() - lp.stat().st_mtime < LOCK_TTL:
        raise HTTPException(409, "The file is being converted and cannot be deleted right now.")
    try:
        p.unlink()
    except PermissionError:
        raise HTTPException(403, "No permission to delete: the file or folder belongs to another user on the NAS. "
                                 "Open up the permissions on the NAS (chmod a+rwX) or delete the file there.")
    except OSError as e:
        raise HTTPException(500, f"Delete failed: {e}")
    parent = p.parent
    base, _ = out_dir()
    if parent.resolve() != base.resolve():
        try:
            parent.rmdir()
        except OSError:
            pass
    return {"ok": True}
