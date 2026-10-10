"""Rippen (MKV oder Disc-Backup) in den Zwischenspeicher."""
import asyncio
import os
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app import ext
from app.config import CONVERT, READY, STAGING, WORK
from app.convert import clean_convert, enqueue_convert
from app.drives import CDROM_EJECT, Drive, device_lost, get_drive, tray, wait_ready
from app.files import out_dir
from app.makemkv import Parser, run_makemkv
from app.state import ACTIVE, CV_ACTIVE, broadcast, conversions, settings, uploads
from app.upload import enqueue_upload, staging_free
from app.util import fmt_bytes, safe_name, unique_path


router = APIRouter()


class RipTitle(BaseModel):
    id: int
    name: str = ""


class RipReq(BaseModel):
    titles: list[RipTitle] = []
    folder: str = ""
    mode: str = "mkv"    # mkv | backup
    convert: dict | None = None   # Konvertierung nach dem Rippen (nur mkv)


async def title_done(drive: Drive, title: dict, folder: str, final: Path, mode: str, converting: bool):
    """Meldet einen fertig gerippten Titel an die Rip-Hooks (ext.register_rip_hook), z. B. für die Medienerkennung."""
    if ext.rip_hooks:
        await ext.run_hooks(ext.rip_hooks, {"dev": drive.dev, "disc": drive.disc, "title": title, "rel": f"{folder}/{final.name}",
                                            "folder": folder, "file": str(final), "mode": mode, "converting": converting})


async def wait_for_space(drive: Drive, job: dict, need: int):
    """Wartet, bis im Zwischenspeicher Platz ist (laufende Übertragungen geben Platz frei)."""
    while staging_free() < need:
        if not any(u["status"] in ACTIVE for u in uploads) and not any(c["status"] in CV_ACTIVE for c in conversions):
            raise OSError(f"Zu wenig Platz im Zwischenspeicher ({STAGING}): {fmt_bytes(staging_free())} frei, {fmt_bytes(need)} nötig")
        job.update(text="Warte auf Konvertierung/Übertragung (Platz im Zwischenspeicher) …", cur=0, total=0)
        broadcast()
        if drive.cancel:
            return
        await asyncio.sleep(5)


async def do_rip(drive: Drive, req: RipReq, dest: Path):
    disc = drive.disc
    by_id = {t["id"]: t for t in disc["titles"]}
    todo = [t for t in req.titles if t.id in by_id]
    backup = req.mode == "backup"
    cfg = clean_convert(req.convert) if (req.convert and not backup and req.convert.get("convert")) else None
    folder = dest.name
    total_bytes = sum(by_id[t.id]["bytes"] for t in todo) or 1
    job = {"kind": "backup" if backup else "rip", "text": "Starte …", "sub": "", "cur": 0, "total": 0,
           "overall": 0.0, "started": time.time(), "dest": str(dest), "index": 0, "count": 1 if backup else len(todo),
           "title": "", "done": [], "failed": 0, "bytes": total_bytes}
    drive.job = job
    drive.log.clear()
    drive.last_msg = ("", 0)
    drive.error = ""
    broadcast()
    ok = True
    work = WORK / f"{int(time.time())}-{Path(drive.dev).name}"
    try:
        work.mkdir(parents=True, exist_ok=True)
        if backup:
            await wait_for_space(drive, job, 55 * 2**30)
            bdir = work / folder
            bdir.mkdir()
            p = Parser(drive, job)
            await run_makemkv(drive, ["info", "disc:9999"], p)      # Laufwerksliste -> disc:N (backup kennt kein dev:)
            idx = p.disc_index
            if idx is None:
                raise RuntimeError(f"Laufwerk {drive.dev} wurde von MakeMKV nicht gefunden")
            drive.log.clear()
            drive.last_msg = ("", 0)
            p = Parser(drive, job)
            tracker = asyncio.create_task(track_overall(job, lambda: job["total"]))
            rc = await run_makemkv(drive, ["backup", "--decrypt", f"disc:{idx}", str(bdir)], p)
            tracker.cancel()
            ok = rc == 0 and not drive.cancel
            if ok:
                rd = unique_path(READY / folder)
                READY.mkdir(parents=True, exist_ok=True)
                os.replace(bdir, rd)
                for e in sorted(rd.iterdir()):
                    enqueue_upload(e, f"{folder}/{e.name}", drive.dev)
                job["done"].append({"name": folder + " (Disc-Backup)", "bytes": 0})
        else:
            done_bytes = 0
            for i, t in enumerate(todo):
                if drive.cancel:
                    ok = False
                    break
                info = by_id[t.id]
                await wait_for_space(drive, job, int(info["bytes"] * 1.05) + 2 * 2**30)
                if drive.cancel:
                    ok = False
                    break
                job.update(index=i + 1, title=t.name or info["name"], cur=0, total=0, text=f"Titel {i+1}/{len(todo)}")
                for x in work.glob("*.mkv"):
                    x.unlink(missing_ok=True)
                p = Parser(drive, job)
                base = done_bytes
                w = info["bytes"] or 1

                async def upd(base=base, w=w):
                    while True:
                        job["overall"] = min(1.0, (base + job["total"] * w) / total_bytes)
                        await asyncio.sleep(0.5)

                tracker = asyncio.create_task(upd())
                for attempt in range(3):
                    rc = await run_makemkv(drive, [f"--minlength={disc['minlength']}", "mkv", f"dev:{drive.dev}", str(t.id), str(work)], p)
                    new = sorted(work.glob("*.mkv"))
                    if drive.cancel or (rc == 0 and new) or attempt == 2 or not device_lost(p, drive):
                        break
                    for x in new:
                        x.unlink(missing_ok=True)
                    drive.add_log("Laufwerk hat sich zurückgesetzt – warte und versuche den Titel erneut …", "error")
                    job.update(text="Laufwerk wird neu verbunden …", cur=0, total=0)
                    broadcast()
                    if not await wait_ready(drive):
                        break
                    p = Parser(drive, job)
                tracker.cancel()
                if drive.cancel:
                    ok = False
                    break
                if rc != 0 or not new:
                    job["failed"] += 1
                    ok = False
                    for x in new:
                        x.unlink(missing_ok=True)
                    drive.add_log(f"Titel {t.id} fehlgeschlagen (Exit-Code {rc})", "error")
                    continue
                f = new[0]
                want = safe_name(t.name, "") if t.name.strip() else ""
                if cfg:                       # erst konvertieren, dann übertragen
                    cdir = CONVERT / folder
                    cdir.mkdir(parents=True, exist_ok=True)
                    final = unique_path(cdir / ((want or f.stem) + ".mkv"))
                    os.replace(f, final)
                    done_bytes += info["bytes"]
                    job["overall"] = min(1.0, done_bytes / total_bytes)
                    job["done"].append({"name": final.name, "bytes": final.stat().st_size})
                    drive.add_log(f"Fertig gerippt: {final.name} ({fmt_bytes(final.stat().st_size)}) – Konvertierung eingereiht", "ok")
                    enqueue_convert(final, folder, cfg, drive.dev)
                    await title_done(drive, info, folder, final, "mkv", True)
                    continue
                rdir = READY / folder
                rdir.mkdir(parents=True, exist_ok=True)
                final = unique_path(rdir / ((want or f.stem) + ".mkv"))
                os.replace(f, final)          # fertig -> ab in die Warteschlange, Laufwerk liest schon den nächsten Titel
                done_bytes += info["bytes"]
                job["overall"] = min(1.0, done_bytes / total_bytes)
                job["done"].append({"name": final.name, "bytes": final.stat().st_size})
                drive.add_log(f"Fertig gerippt: {final.name} ({fmt_bytes(final.stat().st_size)}) – Übertragung läuft im Hintergrund", "ok")
                enqueue_upload(final, f"{folder}/{final.name}", drive.dev)
                await title_done(drive, info, folder, final, "mkv", False)
        if drive.cancel:
            drive.error = "Abgebrochen"
        elif not ok:
            drive.error = "Es sind Fehler aufgetreten – siehe Protokoll"
        else:
            drive.add_log("Alles fertig gerippt.", "ok")
    except Exception as e:  # noqa: BLE001
        drive.error = f"Rip fehlgeschlagen: {e}"
        ok = False
    finally:
        was_cancel = drive.cancel
        drive.cancel = False
        drive.job = None
        shutil.rmtree(work, ignore_errors=True)
        broadcast()
    if ok and not was_cancel and settings["auto_eject"]:
        await asyncio.sleep(1)
        try:
            tray(drive.dev, CDROM_EJECT)
            drive.add_log("Disc ausgeworfen.", "ok")
        except OSError as e:
            drive.add_log(f"Auswerfen fehlgeschlagen: {e}", "error")
        broadcast()


async def track_overall(job, get):
    while True:
        job["overall"] = get()
        await asyncio.sleep(0.5)


@router.post("/api/drives/{n}/rip")
async def api_rip(n: str, req: RipReq):
    dr = get_drive(n)
    if dr.busy:
        raise HTTPException(409, "Laufwerk ist beschäftigt")
    if not dr.disc:
        raise HTTPException(409, "Disc wurde noch nicht analysiert")
    if req.mode not in ("mkv", "backup"):
        raise HTTPException(400, "Unbekannter Modus")
    if req.mode == "mkv" and not req.titles:
        raise HTTPException(400, "Keine Titel gewählt")
    base, _ = out_dir()
    folder = safe_name(req.folder or dr.disc["name"] or dr.disc["volume"])
    dest = base / folder
    need = sum(t["bytes"] for t in dr.disc["titles"] if t["id"] in {x.id for x in req.titles}) if req.mode == "mkv" else 50 * 2**30
    if shutil.disk_usage(base).free < need * 1.02:
        raise HTTPException(507, f"Zu wenig Speicherplatz in {base}")
    biggest = max([t["bytes"] for t in dr.disc["titles"] if t["id"] in {x.id for x in req.titles}] or [0]) if req.mode == "mkv" else 55 * 2**30
    uploading = sum(max(0, u["size"] - u["copied"]) for u in uploads if u["status"] in ACTIVE)
    factor = 1.7 if (req.convert and req.convert.get('convert') and req.mode == 'mkv') else 1.05
    if staging_free() + uploading < biggest * factor:
        raise HTTPException(507, f"Zu wenig Platz im Zwischenspeicher {STAGING}")
    asyncio.create_task(do_rip(dr, req, dest))
    return {"ok": True, "dest": str(dest)}
