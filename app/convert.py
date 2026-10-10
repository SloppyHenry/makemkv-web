"""Konvertierung nach dem Rippen: Warteschlange, Worker, Abbrechen/Überspringen."""
import asyncio
import json
import os
import re
import time
from pathlib import Path
import signal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app import upload
from app import ext
from app.config import CONVERT, CONVERT_DEFAULT, CONV_WORK, READY, REPLACE_DIR, SEG_MIN_SECONDS, X265_PRESETS
from app.ffmpeg import SkipConversion, convert_segments, convert_single, detect_crop, probe, set_conv_paused, signal_all
from app.files import release_lock
from app.state import CV_ACTIVE, broadcast, convert_queue, conversions, conv_procs, conv_state, drives, settings
from app.util import fmt_bytes, unique_path


router = APIRouter()
ext.allow_proxy(r"conversions/pause")
ext.allow_proxy(r"conversions/\d+/skip")
ext.allow_proxy(r"conversions/\d+/cancel")


def choose_segments(dur: float) -> tuple[int, str]:
    """Entscheidet pro Konvertierung, ob (und in wie viele Segmente) geteilt wird – nach tatsächlich freien Kernen und freiem RAM.
    Einstellung conv_segments: 0 = automatisch, 1 = nie teilen, >1 = fest."""
    fixed = int(settings.get("conv_segments", 0))
    if dur < SEG_MIN_SECONDS:
        return 1, "kurzer Titel"
    if fixed >= 1:
        return fixed, "fest eingestellt" if fixed > 1 else "Segmentierung aus"
    cores = os.cpu_count() or 4
    try:
        free_cores = max(0.0, cores - os.getloadavg()[0])
    except OSError:
        free_cores = cores / 2
    try:
        with open("/proc/meminfo") as f:
            mem_gb = next(int(l.split()[1]) for l in f if l.startswith("MemAvailable")) / 1048576
    except (OSError, StopIteration, ValueError):
        mem_gb = 4.0
    n = int(min(free_cores // 4, mem_gb // 2.5, 8))            # ~4 Kerne und ~2,5 GB RAM je Segment
    reason = f"auto: {cores} Kerne, ca. {free_cores:.0f} frei, {mem_gb:.0f} GB RAM frei"
    return (n, reason) if n >= 2 else (1, reason)


def clean_convert(c: dict) -> dict:
    """Prüft/ergänzt eine Konvertierungs-Konfiguration (kommt aus dem Browser)."""
    d = dict(CONVERT_DEFAULT)
    c = c if isinstance(c, dict) else {}
    d["convert"] = bool(c.get("convert", d["convert"]))
    try:
        d["rf"] = max(14, min(30, int(c.get("rf", d["rf"]))))
    except (TypeError, ValueError):
        pass
    if c.get("preset") in X265_PRESETS:
        d["preset"] = c["preset"]
    if c.get("tune") in ("none", "grain", "film", "animation", "stillimage"):
        d["tune"] = c["tune"]
    extra = str(c.get("extra", d["extra"])).strip()
    d["extra"] = extra if re.fullmatch(r"[A-Za-z0-9_=:.,\-]*", extra) else CONVERT_DEFAULT["extra"]
    if c.get("audio") in ("copy", "ac3", "eac3", "aac", "opus"):
        d["audio"] = c["audio"]
    return d


_cv_seq = 0


def next_conversion_id() -> int:
    global _cv_seq
    _cv_seq += 1
    return _cv_seq


def enqueue_convert(src: Path, folder: str, cfg: dict, dev: str = ""):
    cid = next_conversion_id()
    src.with_name(src.name + ".json").write_text(json.dumps(cfg))
    conversions.append({"id": cid, "name": f"{folder}/{src.name}", "folder": folder, "src": str(src), "size_in": src.stat().st_size,
                        "size_out": 0, "status": "queued", "pct": 0.0, "fps": 0.0, "speed": 0.0, "eta": 0, "error": "",
                        "cfg": cfg, "dev": dev, "t": time.time(), "started": 0, "mode": "", "origin": "", "paused": False, "handed": "", "cancel": False})
    convert_queue.put_nowait(conversions[-1])
    broadcast()


async def convert_one(item: dict) -> Path:
    src, cfg = Path(item["src"]), item["cfg"]
    info = await probe(src)
    dur = float(info["format"]["duration"])
    v = next(x for x in info["streams"] if x["codec_type"] == "video")
    item.update(status="running", pct=0.0, fps=0.0, speed=0.0, eta=0, started=time.time())
    broadcast()
    crop = await detect_crop(src, dur, int(v["width"]), int(v["height"]))
    if item["status"] == "skipped":
        raise SkipConversion()
    if item.get("origin") == "library" and upload.staging_free() < item["size_in"]:
        raise OSError(f"Zu wenig Platz im Zwischenspeicher für das Ergebnis ({fmt_bytes(upload.staging_free())} frei)")
    nseg, why = choose_segments(dur) if item.get("attempt", 1) == 1 else (1, "zweiter Versuch")
    item["mode"] = (f"{nseg} Segmente parallel" if nseg > 1 else "ein Prozess") + f" ({why})"
    CONV_WORK.mkdir(parents=True, exist_ok=True)
    out = CONV_WORK / f"{item['id']}.mkv"
    if nseg > 1:
        await convert_segments(item, src, cfg, info, dur, crop, nseg, out)
    else:
        await convert_single(item, src, cfg, info, dur, crop, out)
    oi = await probe(out)
    od = float(oi["format"]["duration"])
    if abs(od - dur) > max(2.0, dur * 0.01):
        out.unlink(missing_ok=True)
        raise OSError(f"Ergebnis hat falsche Länge ({od:.0f}s statt {dur:.0f}s)")
    cnt = lambda pr, t: sum(1 for x in pr["streams"] if x["codec_type"] == t)      # noqa: E731
    if (cnt(info, "audio"), cnt(info, "subtitle")) != (cnt(oi, "audio"), cnt(oi, "subtitle")):
        out.unlink(missing_ok=True)
        raise OSError("Anzahl der Audio-/Untertitelspuren weicht vom Original ab")
    return out


def release_original(item: dict):
    """Original unverändert in die Übertragung geben (Konvertierung übersprungen/fehlgeschlagen) – nichts geht verloren."""
    src = Path(item["src"])
    if src.exists():
        rdir = READY / item["folder"]
        rdir.mkdir(parents=True, exist_ok=True)
        final = unique_path(rdir / src.name)
        os.replace(src, final)
        handover = item.get("handover")
        then = {**handover, "cfg": item["cfg"]} if handover else None     # nach der Übertragung beim anderen Rechner anmelden
        upload.enqueue_upload(final, f"{item['folder']}/{final.name}", item["dev"], then_convert=then)
    src.with_name(src.name + ".json").unlink(missing_ok=True)
    try:
        src.parent.rmdir()
    except OSError:
        pass


conv_running = 0


def ensure_conv_workers():
    """So viele Konvertierungs-Worker laufen lassen, wie in den Einstellungen steht."""
    global conv_running
    while conv_running < int(settings["conv_parallel"]):
        conv_running += 1
        ensure_conv_workers()


async def convert_worker():
    global conv_running
    while True:
        if conv_running > int(settings["conv_parallel"]):      # Einstellung wurde verkleinert
            conv_running -= 1
            return
        item = await convert_queue.get()
        dr = drives.get(item["dev"])
        if item["status"] == "cancelled":
            continue
        while conv_state["paused"] and item["status"] == "queued":      # pausiert: nichts Neues starten
            await asyncio.sleep(1)
        if item["status"] == "cancelled":
            continue
        if item["status"] != "skipped":
            for attempt in (1, 2):
                try:
                    item["attempt"] = attempt
                    out = await convert_one(item)
                    if item.get("origin") == "library":          # Ergebnis ersetzt später das Original auf dem NAS
                        REPLACE_DIR.mkdir(parents=True, exist_ok=True)
                        dest_f = REPLACE_DIR / f"{item['id']}-{Path(item['rel']).name}"
                        os.replace(out, dest_f)
                        item.update(status="done", pct=1.0, eta=0, size_out=dest_f.stat().st_size, t=time.time())
                        upload.enqueue_upload(dest_f, item["rel"], "", replace=True, lock=item["lock"], orig_size=item["size_in"])
                        break
                    src = Path(item["src"])
                    rdir = READY / item["folder"]
                    rdir.mkdir(parents=True, exist_ok=True)
                    final = unique_path(rdir / src.name)
                    os.replace(out, final)
                    size_in = item["size_in"]
                    src.unlink(missing_ok=True)
                    src.with_name(src.name + ".json").unlink(missing_ok=True)
                    try:
                        src.parent.rmdir()
                    except OSError:
                        pass
                    item.update(status="done", pct=1.0, eta=0, size_out=final.stat().st_size, t=time.time())
                    if dr:
                        dr.add_log(f"Konvertiert: {final.name} ({fmt_bytes(size_in)} → {fmt_bytes(item['size_out'])})", "ok")
                    upload.enqueue_upload(final, f"{item['folder']}/{final.name}", item["dev"])
                    break
                except SkipConversion:
                    break
                except Exception as e:  # noqa: BLE001
                    item["error"] = str(e)[:400]
                    if dr:
                        dr.add_log(f"Konvertierung von {item['name']} fehlgeschlagen: {item['error']}", "error")
                    if attempt == 1:
                        item.update(status="queued", pct=0.0)
                        broadcast()
        if item["status"] != "done" and item.get("cancel"):             # Abbrechen: Auftrag beenden, nichts weiterreichen
            finalize_cancel(item)
            broadcast()
            continue
        if item["status"] != "done":
            was_skipped = item["status"] == "skipped"
            if item.get("origin") == "library":              # Original liegt unverändert auf dem NAS
                release_lock(item["lock"])
                item["status"] = "skipped" if was_skipped else "error"
                if not was_skipped:
                    item["error"] += " – Original bleibt unverändert"
                broadcast()
                continue
            release_original(item)
            item["status"] = "skipped" if was_skipped else "error"
            if not was_skipped:
                item["error"] += " – Original wird unverändert übertragen"
            if dr:
                dr.add_log(f"{item['name']}: Original wird unverändert übertragen", "info")
        broadcast()


def discard_staged(item: dict):
    """Eine noch lokal zwischengespeicherte, gerippte Datei verwerfen (nur unterhalb des Konvertierungs-Ordners)."""
    src = Path(item["src"])
    if CONVERT.resolve() in src.resolve().parents:
        src.unlink(missing_ok=True)
        src.with_name(src.name + ".json").unlink(missing_ok=True)
        try:
            src.parent.rmdir()
        except OSError:
            pass


def finalize_cancel(item: dict):
    if item["status"] == "cancelled":
        return
    if item.get("origin") == "library":
        release_lock(item["lock"])                                       # Original bleibt unverändert auf dem NAS
    else:
        discard_staged(item)                                             # frisch gerippte Datei wird verworfen
    item["status"] = "cancelled"
    item["t"] = time.time()
    dr = drives.get(item.get("dev", ""))
    if dr:
        dr.add_log(f"{item['name']}: abgebrochen", "info")


def cancel_conversion(item: dict):
    item["cancel"] = True
    if item["status"] == "queued":                                       # noch nicht gestartet: sofort erledigen
        finalize_cancel(item)
    else:                                                                # läuft: ffmpeg beenden, der Worker räumt auf
        skip_conversion(item)


def skip_conversion(item: dict):
    item["status"] = "skipped"
    item["t"] = time.time()
    for proc in conv_procs.get(item["id"], []):
        if proc.returncode is None:
            proc.terminate()
            if conv_state["paused"]:
                signal_all([proc], signal.SIGCONT)      # ein angehaltener Prozess nimmt SIGTERM erst nach SIGCONT an


class PauseReq(BaseModel):
    paused: bool


@router.post("/api/conversions/pause")
async def api_conv_pause(req: PauseReq):
    set_conv_paused(req.paused)
    broadcast()
    return {"ok": True, "paused": conv_state["paused"]}


@router.post("/api/conversions/{cid}/cancel")
async def api_conv_cancel(cid: int):
    item = next((c for c in conversions if c["id"] == cid), None)
    if not item or item["status"] not in CV_ACTIVE:
        raise HTTPException(404, "Keine laufende oder wartende Konvertierung")
    cancel_conversion(item)
    broadcast()
    return {"ok": True}


@router.post("/api/conversions/{cid}/skip")
async def api_conv_skip(cid: int):
    item = next((c for c in conversions if c["id"] == cid), None)
    if not item or item["status"] not in CV_ACTIVE:
        raise HTTPException(404, "Keine laufende oder wartende Konvertierung")
    skip_conversion(item)
    broadcast()
    return {"ok": True}
