"""Ripping (MKV or disc backup) into the staging buffer."""
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
    convert: dict | None = None   # conversion after ripping (mkv only)


async def title_done(drive: Drive, title: dict, folder: str, final: Path, mode: str, converting: bool):
    """Reports a finished ripped title to the rip hooks (ext.register_rip_hook), e.g. for media detection."""
    if ext.rip_hooks:
        await ext.run_hooks(ext.rip_hooks, {"dev": drive.dev, "disc": drive.disc, "title": title, "rel": f"{folder}/{final.name}",
                                            "folder": folder, "file": str(final), "mode": mode, "converting": converting})


async def wait_for_space(drive: Drive, job: dict, need: int):
    """Waits until there is room in the staging buffer (running transfers free up space)."""
    while staging_free() < need:
        if not any(u["status"] in ACTIVE for u in uploads) and not any(c["status"] in CV_ACTIVE for c in conversions):
            raise OSError(f"Not enough space in the staging buffer ({STAGING}): {fmt_bytes(staging_free())} free, {fmt_bytes(need)} needed")
        job.update(text="Waiting for conversion/transfer (space in the staging buffer) …", cur=0, total=0)
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
    job = {"kind": "backup" if backup else "rip", "text": "Starting …", "sub": "", "cur": 0, "total": 0,
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
            await run_makemkv(drive, ["info", "disc:9999"], p)      # drive list -> disc:N (backup does not know dev:)
            idx = p.disc_index
            if idx is None:
                raise RuntimeError(f"Drive {drive.dev} was not found by MakeMKV")
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
                job["done"].append({"name": folder + " (disc backup)", "bytes": 0})
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
                job.update(index=i + 1, title=t.name or info["name"], cur=0, total=0, text=f"Title {i+1}/{len(todo)}")
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
                    drive.add_log("Drive reset itself – waiting and trying the title again …", "error")
                    job.update(text="Reconnecting drive …", cur=0, total=0)
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
                    drive.add_log(f"Title {t.id} failed (exit code {rc})", "error")
                    continue
                f = new[0]
                want = safe_name(t.name, "") if t.name.strip() else ""
                if cfg:                       # convert first, then transfer
                    cdir = CONVERT / folder
                    cdir.mkdir(parents=True, exist_ok=True)
                    final = unique_path(cdir / ((want or f.stem) + ".mkv"))
                    os.replace(f, final)
                    done_bytes += info["bytes"]
                    job["overall"] = min(1.0, done_bytes / total_bytes)
                    job["done"].append({"name": final.name, "bytes": final.stat().st_size})
                    drive.add_log(f"Ripped: {final.name} ({fmt_bytes(final.stat().st_size)}) – conversion queued", "ok")
                    enqueue_convert(final, folder, cfg, drive.dev)
                    await title_done(drive, info, folder, final, "mkv", True)
                    continue
                rdir = READY / folder
                rdir.mkdir(parents=True, exist_ok=True)
                final = unique_path(rdir / ((want or f.stem) + ".mkv"))
                os.replace(f, final)          # done -> into the queue, the drive is already reading the next title
                done_bytes += info["bytes"]
                job["overall"] = min(1.0, done_bytes / total_bytes)
                job["done"].append({"name": final.name, "bytes": final.stat().st_size})
                drive.add_log(f"Ripped: {final.name} ({fmt_bytes(final.stat().st_size)}) – transfer running in the background", "ok")
                enqueue_upload(final, f"{folder}/{final.name}", drive.dev)
                await title_done(drive, info, folder, final, "mkv", False)
        if drive.cancel:
            drive.error = "Cancelled"
        elif not ok:
            drive.error = "Errors occurred – see the log"
        else:
            drive.add_log("All titles ripped.", "ok")
    except Exception as e:  # noqa: BLE001
        drive.error = f"Rip failed: {e}"
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
            drive.add_log("Disc ejected.", "ok")
        except OSError as e:
            drive.add_log(f"Eject failed: {e}", "error")
        broadcast()


async def track_overall(job, get):
    while True:
        job["overall"] = get()
        await asyncio.sleep(0.5)


def prepare_rip(dr: Drive, req: RipReq) -> Path:
    """Checks the job, space in the target and in the staging buffer (HTTPException on errors) and returns the target folder."""
    if dr.busy:
        raise HTTPException(409, "Drive is busy")
    if not dr.disc:
        raise HTTPException(409, "Disc has not been analyzed yet")
    if req.mode not in ("mkv", "backup"):
        raise HTTPException(400, "Unknown mode")
    if req.mode == "mkv" and not req.titles:
        raise HTTPException(400, "No titles selected")
    base, _ = out_dir()
    folder = safe_name(req.folder or dr.disc["name"] or dr.disc["volume"])
    dest = base / folder
    need = sum(t["bytes"] for t in dr.disc["titles"] if t["id"] in {x.id for x in req.titles}) if req.mode == "mkv" else 50 * 2**30
    if shutil.disk_usage(base).free < need * 1.02:
        raise HTTPException(507, f"Not enough storage space in {base}")
    biggest = max([t["bytes"] for t in dr.disc["titles"] if t["id"] in {x.id for x in req.titles}] or [0]) if req.mode == "mkv" else 55 * 2**30
    uploading = sum(max(0, u["size"] - u["copied"]) for u in uploads if u["status"] in ACTIVE)
    factor = 1.7 if (req.convert and req.convert.get('convert') and req.mode == 'mkv') else 1.05
    if staging_free() + uploading < biggest * factor:
        raise HTTPException(507, f"Not enough space in the staging buffer {STAGING}")
    return dest


@router.post("/api/drives/{n}/rip")
async def api_rip(n: str, req: RipReq):
    dr = get_drive(n)
    dest = prepare_rip(dr, req)
    asyncio.create_task(do_rip(dr, req, dest))
    return {"ok": True, "dest": str(dest)}
