"""ffmpeg/ffprobe: arguments, progress, segments, pause."""
import asyncio
import json
import os
import re
import shutil
import time
from pathlib import Path
import signal
from collections import deque
from app import ffmpeg_errors
from app.config import CONV_WORK
from app.ffmpeg_args import changes_framecount, ffmpeg_args, mux_args, segment_args, two_pass
from app.state import broadcast, conv_procs, conv_state, conversions


def signal_all(procs: list, sig: int):
    for pr in procs:
        if pr.returncode is None:
            try:
                pr.send_signal(sig)
            except ProcessLookupError:
                pass


def set_conv_paused(paused: bool):
    """Stop or resume all running ffmpeg processes; new jobs only start after resuming."""
    conv_state["paused"] = paused
    for procs in conv_procs.values():
        signal_all(procs, signal.SIGSTOP if paused else signal.SIGCONT)
    for c in conversions:
        if c["status"] == "running":
            c["paused"] = paused


def apply_pause(procs: list):
    """Stop freshly started processes right away if paused at the moment."""
    if conv_state["paused"]:
        signal_all(procs, signal.SIGSTOP)


_cv_seq = 0
CV_ACTIVE = ("queued", "running")


class SkipConversion(Exception):
    pass


async def probe(path: Path) -> dict:
    p = await asyncio.create_subprocess_exec("ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", "-show_chapters", str(path),
                                             stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await p.communicate()
    if p.returncode:
        raise OSError("ffprobe: " + err.decode(errors="replace")[-300:])
    return json.loads(out)


async def detect_crop(src: Path, dur: float, w: int, h: int):
    """Detect black bars automatically (5 samples, largest common picture area)."""
    boxes = []
    for f in (0.1, 0.3, 0.5, 0.7, 0.9):
        p = await asyncio.create_subprocess_exec("nice", "-n", "10", "ffmpeg", "-hide_banner", "-nostdin", "-ss", str(int(dur * f)), "-i", str(src),
                                                 "-t", "8", "-vf", "cropdetect=limit=24:round=2:reset=0", "-an", "-sn", "-f", "null", "-",
                                                 stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, err = await p.communicate()
        m = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", err.decode(errors="replace"))
        if m:
            boxes.append(tuple(int(x) for x in m[-1]))
    if not boxes:
        return None
    x1, y1 = min(b[2] for b in boxes), min(b[3] for b in boxes)
    x2, y2 = max(b[2] + b[0] for b in boxes), max(b[3] + b[1] for b in boxes)
    cw, ch = (x2 - x1) // 2 * 2, (y2 - y1) // 2 * 2
    if cw <= 0 or ch <= 0 or (cw, ch) == (w, h) or cw * ch < w * h * 0.5:
        return None
    return f"crop={cw}:{ch}:{x1}:{y1}"


async def detect_scan(src: Path, dur: float) -> str:
    """Detect interlacing (idet at three positions): 'progressive', 'interlaced' or 'telecine' (3:2 pulldown, needs IVTC)."""
    tff = bff = prog = top = bot = neither = 0
    for f in (0.25, 0.5, 0.75):
        p = await asyncio.create_subprocess_exec("nice", "-n", "10", "ffmpeg", "-hide_banner", "-nostdin", "-ss", str(int(dur * f)), "-i", str(src), "-t", "12",
                                                 "-vf", "idet", "-an", "-sn", "-f", "null", "-", stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, err = await p.communicate()
        t = err.decode(errors="replace")
        m = re.search(r"Multi frame detection: TFF:\s*(\d+)\s*BFF:\s*(\d+)\s*Progressive:\s*(\d+)", t)
        r = re.search(r"Repeated Fields: Neither:\s*(\d+)\s*Top:\s*(\d+)\s*Bottom:\s*(\d+)", t)
        if m:
            tff, bff, prog = tff + int(m[1]), bff + int(m[2]), prog + int(m[3])
        if r:
            neither, top, bot = neither + int(r[1]), top + int(r[2]), bot + int(r[3])
    n = tff + bff + prog
    if n < 20 or (tff + bff) / n < 0.25:
        return "progressive"
    rep = (top + bot) / max(1, top + bot + neither)
    return "telecine" if rep > 0.1 else "interlaced"


def _frac(v: str, scale: int) -> int:
    """ffprobe returns fractions like "34000/50000"; x265 wants integers in fixed units."""
    n, _, d = str(v).partition("/")
    return round(float(n) / float(d or 1) * scale)


async def probe_hdr(src: Path) -> dict:
    """HDR10 metadata (mastering display, MaxCLL/MaxFALL) from the first frame of the source; Dolby Vision is only detected (not kept)."""
    p = await asyncio.create_subprocess_exec("ffprobe", "-v", "error", "-select_streams", "v:0", "-read_intervals", "%+#1", "-show_frames", "-print_format", "json",
                                             str(src), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    out, _ = await p.communicate()
    res = {"master": "", "cll": "", "dovi": False}
    try:
        for sd in (json.loads(out).get("frames") or [{}])[0].get("side_data_list", []):
            t = sd.get("side_data_type", "")
            if t.startswith("Mastering display"):
                g = lambda k, sc: _frac(sd[k], sc)       # noqa: E731
                res["master"] = (f"G({g('green_x', 50000)},{g('green_y', 50000)})B({g('blue_x', 50000)},{g('blue_y', 50000)})R({g('red_x', 50000)},{g('red_y', 50000)})"
                                 f"WP({g('white_point_x', 50000)},{g('white_point_y', 50000)})L({g('max_luminance', 10000)},{g('min_luminance', 10000)})")
            elif t.startswith("Content light level"):
                res["cll"] = f"{sd.get('max_content', 0)},{sd.get('max_average', 0)}"
            elif "DOVI" in t or "Dolby Vision" in t:
                res["dovi"] = True
    except (ValueError, KeyError, IndexError, ZeroDivisionError):
        pass
    return res


async def pump(proc, state: dict, key, tail: deque) -> int:
    """Reads the -progress output of an ffmpeg process into state[key] and collects the last error lines."""
    async def err():
        async for raw in proc.stderr:
            tail.append(raw.decode(errors="replace").strip())

    et = asyncio.create_task(err())
    try:
        async for raw in proc.stdout:
            k, _, val = raw.decode(errors="replace").strip().partition("=")
            st = state[key]
            try:
                if k == "out_time_us" and val.lstrip("-").isdigit():
                    st["t"] = int(val) / 1e6
                elif k == "fps":
                    st["fps"] = float(val or 0)
                elif k == "total_size" and val.isdigit():
                    st["size"] = int(val)
            except ValueError:
                pass
        return await proc.wait()
    finally:
        await et


async def aggregate(item: dict, state: dict, dur: float, npass: int = 1, cur: list | None = None):
    """Combine the progress of all (partial) processes into one display. With two passes `cur[0]` counts the running one (0 or 1)."""
    t0 = time.monotonic()
    while True:
        if conv_state["paused"]:                      # paused time does not count towards elapsed time (speed/remaining time)
            t0 += 0.8
            await asyncio.sleep(0.8)
            continue
        base = (cur[0] if cur else 0) * dur
        done = base + sum(s["t"] for s in state.values())
        el = max(1.0, time.monotonic() - t0)
        speed = done / el
        total = dur * npass
        item.update(pct=max(0.0, min(0.97, done / total)), fps=sum(s["fps"] for s in state.values()), speed=speed / npass if npass > 1 else speed,
                    eta=max(0, (total - done) / speed) if speed > 0.001 else 0, size_out=sum(s["size"] for s in state.values()) if npass == 1 or (cur and cur[0] == 1) else 0)
        broadcast()
        await asyncio.sleep(0.8)


async def spawn(args: list[str]):
    return await asyncio.create_subprocess_exec("nice", "-n", "10", *args, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE, limit=2**20)


async def _run_one(item, args: list[str], state: dict, tail: deque) -> int:
    proc = await spawn(args)
    conv_procs[item["id"]] = [proc]
    apply_pause([proc])
    return await pump(proc, state, 0, tail)


async def convert_single(item, src, cfg, ctx, dur, out):
    """One process for the whole movie; with "target size"/"bitrate" and x265/x264 in two passes."""
    passes = [1, 2] if two_pass(cfg) else [0]
    cur, rc = [0], 0
    state, tail = {0: {"t": 0.0, "fps": 0.0, "size": 0}}, deque(maxlen=40)
    ctx = {**ctx, "passlog": str(CONV_WORK / f"{item['id']}-pass")}
    agg = asyncio.create_task(aggregate(item, state, dur, len(passes), cur))
    try:
        for n, p in enumerate(passes):
            cur[0] = n
            state[0].update(t=0.0, fps=0.0, size=0)
            rc = await _run_one(item, ffmpeg_args(src, out, cfg, ctx, p), state, tail)
            if rc != 0 or item["status"] == "skipped":
                break
    finally:
        agg.cancel()
        conv_procs.pop(item["id"], None)
        for f in CONV_WORK.glob(f"{item['id']}-pass*"):
            f.unlink(missing_ok=True)
    if item["status"] == "skipped":
        out.unlink(missing_ok=True)
        raise SkipConversion()
    if rc != 0 or not out.exists():
        out.unlink(missing_ok=True)
        raise OSError(ffmpeg_errors.message("ffmpeg failed", tail))


async def convert_segments(item, src, cfg, ctx, dur, nseg, out):
    """Split the movie into time segments, encode them in parallel, then join them with the original audio/subtitles/chapters."""
    info = ctx["info"]
    v = next(x for x in info["streams"] if x["codec_type"] == "video")
    num, den = (int(x) for x in v["r_frame_rate"].split("/"))
    fps = num / den
    total = round(dur * fps)
    bounds = [round(total * i / nseg) for i in range(nseg + 1)]
    work = CONV_WORK / f"{item['id']}-seg"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    sctx = {**ctx, "pools": max(2, (os.cpu_count() or 4) // nseg)}
    procs, tails, state = [], [], {}
    try:
        for i in range(nseg):
            seek = []
            if i > 0:
                seek += ["-ss", f"{(bounds[i] - 0.5) / fps:.6f}"]       # cut at half a frame boundary: unambiguous, no duplicate/missing frame
            if i < nseg - 1:
                seek += ["-to", f"{(bounds[i + 1] - 0.5) / fps:.6f}"]
            procs.append(await spawn(segment_args(src, work / f"seg{i:02d}.mkv", cfg, sctx, seek, f"{num}/{den}")))
            tails.append(deque(maxlen=30))
            state[i] = {"t": 0.0, "fps": 0.0, "size": 0}
        conv_procs[item["id"]] = procs
        apply_pause(procs)
        agg = asyncio.create_task(aggregate(item, state, dur))
        try:
            rcs = await asyncio.gather(*[pump(p, state, i, tails[i]) for i, p in enumerate(procs)])
        finally:
            agg.cancel()
            conv_procs.pop(item["id"], None)
        if item["status"] == "skipped":
            raise SkipConversion()
        for i, rc in enumerate(rcs):
            if rc != 0:
                raise OSError(ffmpeg_errors.message(f"Segment {i + 1}/{nseg} failed", tails[i], 3))
        for i in range(nseg):                                        # every segment must have the expected length
            want = (bounds[i + 1] - bounds[i]) / fps
            got = float((await probe(work / f"seg{i:02d}.mkv"))["format"]["duration"])
            if abs(got - want) > 2 / fps + 0.3:
                raise OSError(f"Segment {i + 1} has the wrong length ({got:.2f}s instead of {want:.2f}s)")
        item.update(pct=0.98, eta=0, fps=0.0)
        broadcast()
        lst = work / "list.txt"
        lst.write_text("".join(f"file '{work}/seg{i:02d}.mkv'\n" for i in range(nseg)))
        p = await spawn(mux_args(lst, src, out, cfg, info))
        conv_procs[item["id"]] = [p]
        apply_pause([p])
        _, err = await p.communicate()
        conv_procs.pop(item["id"], None)
        if item["status"] == "skipped":
            raise SkipConversion()
        if p.returncode != 0 or not out.exists():
            raise OSError("Joining failed: " + err.decode(errors="replace")[-300:])
        # check the frame count of the result (±1 frame per cut tolerated)
        r = await asyncio.create_subprocess_exec("ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                                                 "stream=nb_read_packets", "-of", "csv=p=0", str(out),
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        o, _ = await r.communicate()
        frames = int(o.decode().strip().split(",")[0] or 0)
        if abs(frames - total) > nseg + 3:
            raise OSError(f"Frame count does not match ({frames} instead of about {total})")
    except BaseException:
        out.unlink(missing_ok=True)
        for pr in procs:
            if pr.returncode is None:
                pr.terminate()
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


__all__ = ["SkipConversion", "convert_segments", "convert_single", "detect_crop", "detect_scan", "probe", "probe_hdr", "set_conv_paused",
           "signal_all", "changes_framecount"]
