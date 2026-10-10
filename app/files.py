"""Ausgabeziel (NAS/Fallback), Pfadprüfung, Sperrdateien und Datei-API."""
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
    """True, wenn OUT_MOUNT ein echter NFS/CIFS-Mount ist (autofs wird dabei angestoßen)."""
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
    """Sperrdatei neben der Datei anlegen (damit nicht zwei Instanzen dieselbe Datei umbauen). Rückgabe: '' = gesperrt, sonst Name des Besitzers."""
    lp = lock_path(p)
    for _ in range(2):
        try:
            fd = os.open(lp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
        except FileExistsError:
            try:
                if time.time() - lp.stat().st_mtime > LOCK_TTL:      # verwaist -> übernehmen
                    lp.unlink(missing_ok=True)
                    continue
                owner = json.loads(lp.read_text()).get("inst", "andere Instanz")
                if takeover_from and owner.lower() == takeover_from.lower():      # Übergabe: der bisherige Besitzer gibt ab
                    lp.unlink(missing_ok=True)
                    continue
            except (OSError, ValueError):
                owner = "andere Instanz"
            return owner
        with os.fdopen(fd, "w") as f:
            json.dump({"inst": INSTANCE, "t": time.time()}, f)
        open_perms(lp, False)
        held_locks.add(str(lp))
        return ""
    return "andere Instanz"


def release_lock(lp: str):
    if not lp:                       # Sperre wurde bei einer Übergabe abgegeben
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
    """Ausgabeziel im Hintergrund prüfen – ein hängendes Netzlaufwerk darf die Oberfläche nicht blockieren."""
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
        raise HTTPException(400, "Ungültiger Pfad")
    return p


def busy_reason(rel: str, is_dir: bool, abs_path: Path) -> str:
    """Warum etwas gerade nicht umbenannt werden darf ('' = darf)."""
    hit = (lambda r: r.startswith(rel + "/")) if is_dir else (lambda r: r == rel)
    if any(c.get("origin") == "library" and c["status"] in CV_ACTIVE and hit(c["rel"]) for c in conversions):
        return "wird gerade konvertiert"
    if any(u["status"] in ACTIVE and (hit(u["name"]) or (is_dir and u["name"].startswith(rel + "/"))) for u in uploads):
        return "wird gerade übertragen"
    if is_dir and any(d.job and str(d.job.get("dest", "")).startswith(str(abs_path)) for d in drives.values()):
        return "wird gerade von einem Rip beschrieben"
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
        raise HTTPException(409, "Die Datei wird gerade konvertiert und kann jetzt nicht gelöscht werden.")
    try:
        p.unlink()
    except PermissionError:
        raise HTTPException(403, "Keine Berechtigung zum Löschen: Datei oder Ordner gehört auf dem NAS einem anderen Benutzer. "
                                 "Auf dem NAS die Rechte öffnen (chmod a+rwX) oder die Datei dort löschen.")
    except OSError as e:
        raise HTTPException(500, f"Löschen fehlgeschlagen: {e}")
    parent = p.parent
    base, _ = out_dir()
    if parent.resolve() != base.resolve():
        try:
            parent.rmdir()
        except OSError:
            pass
    return {"ok": True}
