"""Conversion after ripping: queue, worker, cancel/skip."""
import asyncio
import json
import os
import time
from pathlib import Path
import signal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app import upload
from app import ext
from app import convert_caps, convert_stats
from app.config import CONVERT, CONV_WORK, READY, REPLACE_DIR, SEG_MIN_SECONDS
from app.convert_schema import CODECS, clean_v2, describe
from app.ffmpeg import (SkipConversion, changes_framecount, convert_segments, convert_single, detect_crop, detect_scan, probe, probe_hdr, set_conv_paused,
                        signal_all)
from app.ffmpeg_args import hdr_kept, sub_streams, target_kbps, two_pass
from app.files import release_lock
from app.state import CV_ACTIVE, broadcast, convert_queue, conversions, conv_procs, conv_state, drives, settings
from app.util import fmt_bytes, unique_path


router = APIRouter()
ext.allow_proxy(r"conversions/pause")
ext.allow_proxy(r"conversions/\d+/skip")
ext.allow_proxy(r"conversions/\d+/cancel")


def choose_segments(dur: float) -> tuple[int, str]:
    """Decides per conversion whether to split (and into how many segments) – based on the cores and RAM that are actually free.
    Setting conv_segments: 0 = automatic, 1 = never split, >1 = fixed."""
    fixed = int(settings.get("conv_segments", 0))
    if dur < SEG_MIN_SECONDS:
        return 1, "short title"
    if fixed >= 1:
        return fixed, "fixed setting" if fixed > 1 else "segmentation off"
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
    n = int(min(free_cores // 4, mem_gb // 2.5, 8))            # ~4 cores and ~2.5 GB RAM per segment
    reason = f"auto: {cores} cores, about {free_cores:.0f} free, {mem_gb:.0f} GB RAM free"
    return (n, reason) if n >= 2 else (1, reason)


def clean_convert(c: dict) -> dict:
    """Checks/completes a conversion configuration (comes from the browser, a sidecar file or another machine).
    Accepts the old five fields (v1) and the new schema (v2) and always returns a complete v2 dict including mirrors of the old fields."""
    return clean_v2(c)


class Unsupported(OSError):
    """This setting cannot run on this machine (encoder/filter missing …): no second attempt."""


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
    if why := convert_caps.unusable(cfg, info):
        raise Unsupported(why)
    item.update(status="running", pct=0.0, fps=0.0, speed=0.0, eta=0, started=time.time())
    broadcast()
    codec, pic = cfg["video"]["codec"], cfg["picture"]
    ctx = {"info": info, "dur": dur, "crop": None, "scan": "progressive", "hdr": {}, "pools": 0, "kbps": 0}
    if codec != "copy":
        if pic["crop"] == "auto":
            ctx["crop"] = await detect_crop(src, dur, int(v["width"]), int(v["height"]))
        if pic["deint"] == "auto":
            ctx["scan"] = await detect_scan(src, dur)
        if hdr_kept(cfg, info) and codec == "x265":
            ctx["hdr"] = await probe_hdr(src)
        ctx["kbps"] = target_kbps(cfg, info, dur)
    if item["status"] == "skipped":
        raise SkipConversion()
    if item.get("origin") == "library" and upload.staging_free() < item["size_in"]:
        raise OSError(f"Not enough space in the staging buffer for the result ({fmt_bytes(upload.staging_free())} free)")
    nseg, why = choose_segments(dur) if item.get("attempt", 1) == 1 else (1, "second attempt")
    if nseg > 1 and not CODECS[codec]["segments"]:
        nseg, why = 1, "hardware encoder" if codec == "hw" else "no re-encoding"
    elif nseg > 1 and (two_pass(cfg) or changes_framecount(cfg, ctx)):
        nseg, why = 1, "two passes" if two_pass(cfg) else "telecine removal"
    item["mode"] = (f"{nseg} segments in parallel" if nseg > 1 else "one process") + f" ({why})"
    item["meta"] = {"w": int(v.get("width") or 0), "h": int(v.get("height") or 0), "dur": dur, "nseg": nseg, "src_codec": v.get("codec_name", ""),
                    "fps": _fps(v), "summary": describe(cfg)}
    CONV_WORK.mkdir(parents=True, exist_ok=True)
    out = CONV_WORK / f"{item['id']}.mkv"
    if nseg > 1:
        await convert_segments(item, src, cfg, ctx, dur, nseg, out)
    else:
        await convert_single(item, src, cfg, ctx, dur, out)
    oi = await probe(out)
    od = float(oi["format"]["duration"])
    if abs(od - dur) > max(2.0, dur * 0.01):
        out.unlink(missing_ok=True)
        raise OSError(f"Result has the wrong length ({od:.0f}s instead of {dur:.0f}s)")
    cnt = lambda pr, t: sum(1 for x in pr["streams"] if x["codec_type"] == t)      # noqa: E731
    if (cnt(info, "audio"), len(sub_streams(cfg, info))) != (cnt(oi, "audio"), cnt(oi, "subtitle")):
        out.unlink(missing_ok=True)
        raise OSError("Number of audio/subtitle tracks differs from the original")
    return out


def _fps(v: dict) -> float:
    try:
        n, d = (int(x) for x in str(v.get("r_frame_rate", "0/1")).split("/"))
        return n / d if d else 0.0
    except ValueError:
        return 0.0


def release_original(item: dict):
    """Pass the original on to the transfer unchanged (conversion skipped/failed) – nothing gets lost."""
    src = Path(item["src"])
    if src.exists():
        rdir = READY / item["folder"]
        rdir.mkdir(parents=True, exist_ok=True)
        final = unique_path(rdir / src.name)
        os.replace(src, final)
        handover = item.get("handover")
        then = {**handover, "cfg": item["cfg"]} if handover else None     # register with the other machine after the transfer
        upload.enqueue_upload(final, f"{item['folder']}/{final.name}", item["dev"], then_convert=then)
    src.with_name(src.name + ".json").unlink(missing_ok=True)
    try:
        src.parent.rmdir()
    except OSError:
        pass


conv_running = 0


def ensure_conv_workers():
    """Keep as many conversion workers running as the settings say (files at the same time). Called after every save."""
    global conv_running
    while conv_running < int(settings["conv_parallel"]):
        conv_running += 1
        asyncio.create_task(worker_loop())


async def convert_worker():
    """First worker (started by main.py on startup); more follow via ensure_conv_workers()."""
    global conv_running
    conv_running += 1
    ensure_conv_workers()
    await worker_loop()


async def worker_loop():
    global conv_running
    while True:
        if conv_running > int(settings["conv_parallel"]):      # the setting was reduced
            conv_running -= 1
            return
        item = await convert_queue.get()
        try:
            await process_item(item)
        except Exception as e:  # noqa: BLE001      an error while cleaning up must not end the worker
            print(f"Conversion {item.get('name')}: {e!r}", flush=True)
            item["status"] = "error" if item["status"] not in ("done", "skipped", "cancelled") else item["status"]
            item["error"] = item.get("error") or str(e)[:300]
            broadcast()


async def process_item(item: dict):
    dr = drives.get(item["dev"])
    if item["status"] == "cancelled":
        return
    while conv_state["paused"] and item["status"] == "queued":      # paused: start nothing new
        await asyncio.sleep(1)
    if item["status"] == "cancelled":
        return
    if item["status"] != "skipped":
        for attempt in (1, 2):
            try:
                item["attempt"] = attempt
                out = await convert_one(item)
                if item.get("origin") == "library":          # the result later replaces the original on the NAS
                    REPLACE_DIR.mkdir(parents=True, exist_ok=True)
                    dest_f = REPLACE_DIR / f"{item['id']}-{Path(item['rel']).name}"
                    os.replace(out, dest_f)
                    item.update(status="done", pct=1.0, eta=0, size_out=dest_f.stat().st_size, t=time.time())
                    convert_stats.record(item)
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
                convert_stats.record(item)
                if dr:
                    dr.add_log(f"Converted: {final.name} ({fmt_bytes(size_in)} → {fmt_bytes(item['size_out'])})", "ok")
                upload.enqueue_upload(final, f"{item['folder']}/{final.name}", item["dev"])
                break
            except SkipConversion:
                break
            except Unsupported as e:                                  # can never run here: give up right away, no second attempt
                item["error"] = str(e)[:400]
                if dr:
                    dr.add_log(f"Conversion of {item['name']} not possible: {item['error']}", "error")
                break
            except Exception as e:  # noqa: BLE001
                item["error"] = str(e)[:400]
                if dr:
                    dr.add_log(f"Conversion of {item['name']} failed: {item['error']}", "error")
                if attempt == 1:
                    item.update(status="queued", pct=0.0)
                    broadcast()
    if item["status"] != "done" and item.get("cancel"):             # cancel: end the job, pass nothing on
        finalize_cancel(item)
        broadcast()
        return
    if item["status"] != "done":
        was_skipped = item["status"] == "skipped"
        if item.get("origin") == "library":              # the original stays unchanged on the NAS
            release_lock(item["lock"])
            item["status"] = "skipped" if was_skipped else "error"
            if not was_skipped:
                item["error"] += " – original stays unchanged"
            broadcast()
            return
        release_original(item)
        item["status"] = "skipped" if was_skipped else "error"
        if not was_skipped:
            item["error"] += " – original is transferred unchanged"
        if dr:
            dr.add_log(f"{item['name']}: original is transferred unchanged", "info")
    broadcast()


def discard_staged(item: dict):
    """Discard a ripped file that is still buffered locally (only below the conversion folder)."""
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
        release_lock(item["lock"])                                       # the original stays unchanged on the NAS
    else:
        discard_staged(item)                                             # the freshly ripped file is discarded
    item["status"] = "cancelled"
    item["t"] = time.time()
    dr = drives.get(item.get("dev", ""))
    if dr:
        dr.add_log(f"{item['name']}: cancelled", "info")


def cancel_conversion(item: dict):
    item["cancel"] = True
    if item["status"] == "queued":                                       # not started yet: finish right away
        finalize_cancel(item)
    else:                                                                # running: stop ffmpeg, the worker cleans up
        skip_conversion(item)


def skip_conversion(item: dict):
    item["status"] = "skipped"
    item["t"] = time.time()
    for proc in conv_procs.get(item["id"], []):
        if proc.returncode is None:
            proc.terminate()
            if conv_state["paused"]:
                signal_all([proc], signal.SIGCONT)      # a stopped process only accepts SIGTERM after SIGCONT


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
        raise HTTPException(404, "No running or waiting conversion")
    cancel_conversion(item)
    broadcast()
    return {"ok": True}


@router.post("/api/conversions/{cid}/skip")
async def api_conv_skip(cid: int):
    item = next((c for c in conversions if c["id"] == cid), None)
    if not item or item["status"] not in CV_ACTIVE:
        raise HTTPException(404, "No running or waiting conversion")
    skip_conversion(item)
    broadcast()
    return {"ok": True}
