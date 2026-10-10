"""Laufwerke: Erkennung (ioctl), Analyse, Auswerfen, Hintergrund-Poller."""
import asyncio
import fcntl
import glob
import os
import time
from collections import deque
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app import ext
from app.config import DEV_DRIVE_DIR, HIDE_RE
from app.makemkv import Parser, fetch_beta_key_sync, run_makemkv
from app.state import beta, broadcast, drives, hidden_drives, settings

router = APIRouter()
ext.allow_proxy(r"drives/[A-Za-z0-9]+/(scan|rip|eject|close|cancel)")
DEV_ROOT = DEV_DRIVE_DIR or "/dev"       # Entwicklung (scripts/dev.sh): Attrappen-Laufwerke als Dateien statt /dev/sr*


CDROM_EJECT, CDROM_CLOSE_TRAY, CDROM_DRIVE_STATUS = 0x5309, 0x5319, 0x5326
CDS_NO_DISC, CDS_TRAY_OPEN, CDS_NOT_READY, CDS_DISC_OK = 1, 2, 3, 4


def drive_name(dev: str) -> str:
    base = Path(dev).name
    if DEV_DRIVE_DIR:
        return f"Attrappe BD-ROM ({base})"
    try:
        v = Path(f"/sys/class/block/{base}/device/vendor").read_text().strip()
        m = Path(f"/sys/class/block/{base}/device/model").read_text().strip()
        return f"{v} {m}".strip()
    except OSError:
        return base


def drive_status(dev: str) -> str:
    if DEV_DRIVE_DIR:                       # Datei enthält: ready | empty | open | loading
        try:
            return Path(dev).read_text().strip() or "empty"
        except OSError:
            return "gone"
    try:
        fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return "gone"
    try:
        r = fcntl.ioctl(fd, CDROM_DRIVE_STATUS, 0)
    except OSError:
        return "loading"
    finally:
        os.close(fd)
    return {CDS_NO_DISC: "empty", CDS_TRAY_OPEN: "open", CDS_NOT_READY: "loading", CDS_DISC_OK: "ready"}.get(r, "loading")


def tray(dev: str, req: int):
    if DEV_DRIVE_DIR:
        Path(dev).write_text("open" if req == CDROM_EJECT else "ready")
        return
    fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
    try:
        fcntl.ioctl(fd, req, 0)
    finally:
        os.close(fd)


# ---------------------------------------------------------------- Laufwerk


class Drive:
    def __init__(self, dev: str):
        self.dev = dev
        self.name = drive_name(dev)
        self.status = "unknown"
        self.ready_polls = 0
        self.attempted = False    # für diese Disc wurde ein Scan versucht
        self.scan_id = 0
        self.disc = None
        self.label = ""
        self.error = ""
        self.job = None
        self.proc = None
        self.cancel = False
        self.log = deque(maxlen=300)
        self.last_msg = ("", 0)

    @property
    def busy(self):
        return self.job is not None

    def add_log(self, text: str, level="info"):
        if self.last_msg[0] == text:
            n = self.last_msg[1] + 1
            self.last_msg = (text, n)
            if n in (2, 10, 100, 1000):
                self.log.append({"t": time.strftime("%H:%M:%S"), "l": level, "m": f"… (×{n}) {text}"})
            return
        self.last_msg = (text, 1)
        self.log.append({"t": time.strftime("%H:%M:%S"), "l": level, "m": text})

    def public(self):
        return {
            "id": Path(self.dev).name, "dev": self.dev, "name": self.name, "status": self.status,
            "scan_id": self.scan_id, "disc": self.disc, "label": self.label, "error": self.error,
            "job": self.job, "log": list(self.log)[-120:],
        }


def device_lost(p: "Parser", drive: Drive) -> bool:
    """Das USB-Laufwerk hat sich während des Laufs zurückgesetzt/getrennt."""
    return any("SG:<unknown>" in e or "No such device" in e for e in p.errors) or drive_status(drive.dev) == "gone"


async def wait_ready(drive: Drive, timeout=60) -> bool:
    end = time.monotonic() + timeout
    await asyncio.sleep(2)
    while time.monotonic() < end:
        if await asyncio.to_thread(drive_status, drive.dev) == "ready":
            await asyncio.sleep(2)
            return True
        await asyncio.sleep(1.5)
    return False


async def do_scan(drive: Drive):
    drive.attempted = True
    drive.scan_id += 1
    drive.disc, drive.error = None, ""
    drive.log.clear()
    drive.last_msg = ("", 0)
    drive.job = {"kind": "scan", "text": "Disc wird analysiert …", "cur": 0, "total": 0, "started": time.time()}
    broadcast()
    ml = int(settings["minlength"])
    try:
        if not (settings["key"].strip() or beta["key"]):
            drive.job["text"] = "Hole MakeMKV-Beta-Key …"
            broadcast()
            await asyncio.to_thread(fetch_beta_key_sync)
        for attempt in range(3):
            p = Parser(drive, drive.job)
            rc = await run_makemkv(drive, [f"--minlength={ml}", "info", f"dev:{drive.dev}"], p)
            if drive.cancel:
                drive.error = "Analyse abgebrochen"
                break
            if p.tinfo:
                drive.disc = p.disc(ml)
                if not drive.disc["name"]:
                    drive.disc["name"] = drive.label
                drive.error = ""
                break
            if attempt < 2 and device_lost(p, drive):
                drive.add_log("Laufwerk hat sich zurückgesetzt – warte und versuche es erneut …", "error")
                drive.job.update(text="Laufwerk wird neu verbunden …", cur=0, total=0)
                broadcast()
                if await wait_ready(drive):
                    drive.log.clear()
                    drive.last_msg = ("", 0)
                    drive.job.update(text="Disc wird analysiert …")
                    continue
            drive.error = next((e for e in reversed(p.errors) if "No such device" not in e and "SG:<unknown>" not in e), "") \
                or f"Keine Titel gefunden (Exit-Code {rc}). Disc beschädigt, nicht unterstützt oder Key abgelaufen?"
            break
    except Exception as e:  # noqa: BLE001
        drive.error = f"Analyse fehlgeschlagen: {e}"
    finally:
        drive.cancel = False
        drive.job = None
        broadcast()


async def poller():
    while True:
        try:
            devs = sorted(glob.glob(f"{DEV_ROOT}/sr[0-9]*"))
            changed = False
            hidden_drives.intersection_update(devs)
            for d in devs:
                if d not in drives and d not in hidden_drives:
                    dr = Drive(d)
                    if HIDE_RE and HIDE_RE.search(dr.name):
                        hidden_drives.add(d)
                        continue
                    drives[d] = dr
                    changed = True
            for d, dr in list(drives.items()):
                if dr.busy:
                    continue
                if d not in devs:
                    del drives[d]
                    changed = True
                    continue
                st = await asyncio.to_thread(drive_status, d)
                if st == "gone":
                    continue
                if st != dr.status:
                    dr.status = st
                    changed = True
                    if st in ("empty", "open"):
                        dr.disc, dr.error, dr.label, dr.attempted, dr.ready_polls = None, "", "", False, 0
                        dr.log.clear()
                dr.ready_polls = dr.ready_polls + 1 if st == "ready" else 0
                if st == "ready" and dr.ready_polls >= 2 and not dr.attempted and settings["auto_scan"]:
                    asyncio.create_task(do_scan(dr))
                    changed = True
            if changed:
                broadcast()
        except Exception as e:  # noqa: BLE001
            print("poller:", e, flush=True)
        await asyncio.sleep(1.5)


def get_drive(n: str) -> Drive:
    dr = drives.get(f"{DEV_ROOT}/{n}")
    if not dr:
        raise HTTPException(404, "Laufwerk nicht gefunden")
    return dr


@router.post("/api/drives/{n}/scan")
async def api_scan(n: str):
    dr = get_drive(n)
    if dr.busy:
        raise HTTPException(409, "Laufwerk ist beschäftigt")
    if dr.status != "ready":
        raise HTTPException(409, "Keine Disc im Laufwerk")
    asyncio.create_task(do_scan(dr))
    return {"ok": True}


@router.post("/api/drives/{n}/cancel")
async def api_cancel(n: str):
    dr = get_drive(n)
    if dr.proc:
        dr.cancel = True
        dr.proc.terminate()
        asyncio.get_running_loop().call_later(6, lambda: dr.proc and dr.proc.kill())
    return {"ok": True}


@router.post("/api/drives/{n}/eject")
async def api_eject(n: str):
    dr = get_drive(n)
    if dr.busy:
        raise HTTPException(409, "Laufwerk ist beschäftigt")
    try:
        await asyncio.to_thread(tray, dr.dev, CDROM_EJECT)
    except OSError as e:
        raise HTTPException(500, f"Auswerfen fehlgeschlagen: {e}")
    return {"ok": True}


@router.post("/api/drives/{n}/close")
async def api_close(n: str):
    dr = get_drive(n)
    if dr.busy:
        raise HTTPException(409, "Laufwerk ist beschäftigt")
    try:
        await asyncio.to_thread(tray, dr.dev, CDROM_CLOSE_TRAY)
    except OSError as e:
        raise HTTPException(500, f"Einziehen fehlgeschlagen: {e}")
    return {"ok": True}
