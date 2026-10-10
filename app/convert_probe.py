"""Probe: zwei kurze Ausschnitte (je 25 s) mit den gewählten Einstellungen kodieren, daraus Größe und Dauer genauer hochrechnen
und je ein Standbild Vorher/Nachher liefern (für den Schieberegler im Editor).

POST /api/convert/probe {path, cfg} startet (ein Auftrag zur Zeit, mit `nice`), GET /api/convert/probe/{id} liefert Fortschritt und Ergebnis.
"""
import asyncio
import base64
import shutil
import time
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import convert_caps, convert_stats
from app.config import CONV_WORK
from app.convert_schema import clean_v2
from app.ffmpeg import detect_crop, detect_scan, probe, probe_hdr, spawn
from app.ffmpeg_args import hdr_kept, segment_args, target_kbps
from app.files import inside_out
from app.library_info import lib_info

router = APIRouter()
jobs: dict[str, dict] = {}
SLICE, POINTS, FRAME_AT = 25, (0.25, 0.65), 10


class ProbeReq(BaseModel):
    path: str
    cfg: dict = {}


async def _frame(src, at: float) -> str:
    """Standbild als data:-URL (JPEG, 960 px breit)."""
    p = await asyncio.create_subprocess_exec("ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", f"{at:.2f}", "-i", str(src), "-frames:v", "1", "-vf", "scale=960:-2",
                                             "-q:v", "4", "-f", "mjpeg", "-", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    out, _ = await p.communicate()
    return "data:image/jpeg;base64," + base64.b64encode(out).decode() if out else ""


async def run(job: dict, src, cfg: dict):
    work = CONV_WORK / f"probe-{job['id']}"
    try:
        work.mkdir(parents=True, exist_ok=True)
        info = await probe(src)
        info_l = lib_info(info)
        dur = float(info["format"]["duration"])
        v = next(x for x in info["streams"] if x["codec_type"] == "video")
        if why := convert_caps.unusable(cfg, info):
            raise ValueError(why)
        if cfg["video"]["codec"] == "copy":
            raise ValueError("Beim reinen Remuxen gibt es nichts zu probieren.")
        if dur < SLICE * 3:
            raise ValueError("Die Datei ist zu kurz für eine Probe.")
        ctx = {"info": info, "dur": dur, "crop": None, "scan": "progressive", "hdr": {}, "pools": 0, "kbps": target_kbps(cfg, info, dur)}
        if cfg["picture"]["crop"] == "auto":
            ctx["crop"] = await detect_crop(src, dur, int(v["width"]), int(v["height"]))
        if cfg["picture"]["deint"] == "auto":
            ctx["scan"] = await detect_scan(src, dur)
        if hdr_kept(cfg, info) and cfg["video"]["codec"] == "x265":
            ctx["hdr"] = await probe_hdr(src)
        num, den = (int(x) for x in v["r_frame_rate"].split("/"))
        sizes, secs, frames = 0, 0.0, []
        for n, pt in enumerate(POINTS):
            job.update(pct=n / len(POINTS), text=f"Ausschnitt {n + 1} von {len(POINTS)} …")
            out, start = work / f"p{n}.mkv", dur * pt
            t0 = time.monotonic()
            proc = await spawn(segment_args(src, out, cfg, ctx, ["-ss", f"{start:.2f}", "-t", str(SLICE)], f"{num}/{den}"))
            job["proc"] = proc
            _, err = await proc.communicate()
            if proc.returncode != 0 or not out.exists():
                raise ValueError("Die Probe-Kodierung ist fehlgeschlagen: " + err.decode(errors="replace")[-200:])
            secs += time.monotonic() - t0
            sizes += out.stat().st_size
            if n == 0:
                frames = [await _frame(src, start + FRAME_AT), await _frame(out, FRAME_AT)]
        per_sec = sizes / (SLICE * len(POINTS))
        src_d = {"size": src.stat().st_size, "dur": dur, "w": info_l["w"], "h": info_l["h"], "fps": info_l["fps"], "audio": info_l["audio"], "abytes": info_l["abytes"]}
        est = int(per_sec * dur + convert_stats.audio_out_bytes(cfg, src_d))
        job.update(status="done", pct=1.0, text="", result={"out_bytes": est, "in_bytes": src_d["size"], "slice_s": SLICE, "slices": len(POINTS), "sample_bytes": sizes,
                                                              "secs_here": round(secs / (SLICE * len(POINTS)) * dur), "before": frames[0], "after": frames[1]})
    except (ValueError, OSError, StopIteration, KeyError) as e:
        job.update(status="error", error=str(e)[:300])
    finally:
        job.pop("proc", None)
        shutil.rmtree(work, ignore_errors=True)
        job["t_end"] = time.time()


@router.post("/probe")
async def api_probe(req: ProbeReq):
    if any(j["status"] == "running" for j in jobs.values()):
        raise HTTPException(409, "Es läuft schon eine Probe.")
    src = inside_out(req.path)
    if not src.is_file():
        raise HTTPException(404, "Datei nicht gefunden")
    for k in sorted(jobs, key=lambda k: jobs[k]["t"])[:-8]:
        jobs.pop(k, None)
    job = {"id": uuid.uuid4().hex[:10], "status": "running", "pct": 0.0, "text": "Starte …", "t": time.time()}
    jobs[job["id"]] = job
    asyncio.create_task(run(job, src, clean_v2({**req.cfg, "convert": True})))
    return {"id": job["id"]}


@router.get("/probe/{jid}")
def api_probe_get(jid: str):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(404, "Unbekannte Probe")
    return {k: v for k, v in j.items() if k != "proc"}


@router.post("/probe/{jid}/cancel")
def api_probe_cancel(jid: str):
    j = jobs.get(jid)
    if not j or j["status"] != "running":
        raise HTTPException(404, "Keine laufende Probe")
    proc = j.get("proc")
    if proc and proc.returncode is None:
        proc.terminate()
    j.update(status="error", error="abgebrochen")
    return {"ok": True}
