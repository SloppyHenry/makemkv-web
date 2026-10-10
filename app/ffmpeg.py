"""ffmpeg/ffprobe: Argumente, Fortschritt, Segmente, Pause."""
import asyncio
import json
import os
import re
import shutil
import time
from pathlib import Path
import signal
from collections import deque
from app.config import CONV_WORK
from app.state import broadcast, conv_procs, conv_state, conversions


def signal_all(procs: list, sig: int):
    for pr in procs:
        if pr.returncode is None:
            try:
                pr.send_signal(sig)
            except ProcessLookupError:
                pass


def set_conv_paused(paused: bool):
    """Alle laufenden ffmpeg-Prozesse anhalten bzw. fortsetzen; neue Aufträge starten erst nach dem Fortsetzen."""
    conv_state["paused"] = paused
    for procs in conv_procs.values():
        signal_all(procs, signal.SIGSTOP if paused else signal.SIGCONT)
    for c in conversions:
        if c["status"] == "running":
            c["paused"] = paused


def apply_pause(procs: list):
    """Frisch gestartete Prozesse sofort anhalten, wenn gerade pausiert ist."""
    if conv_state["paused"]:
        signal_all(procs, signal.SIGSTOP)


_cv_seq = 0
CV_ACTIVE = ("queued", "running")


class SkipConversion(Exception):
    pass


async def probe(path: Path) -> dict:
    p = await asyncio.create_subprocess_exec("ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path),
                                             stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await p.communicate()
    if p.returncode:
        raise OSError("ffprobe: " + err.decode(errors="replace")[-300:])
    return json.loads(out)


async def detect_crop(src: Path, dur: float, w: int, h: int):
    """Schwarze Balken automatisch erkennen (5 Stichproben, größter gemeinsamer Bildbereich)."""
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


def x265_args(cfg: dict, pools: int = 0) -> list[str]:
    a = ["-c:v", "libx265", "-preset", cfg["preset"], "-crf", str(cfg["rf"]), "-pix_fmt", "yuv420p10le"]
    if cfg["tune"] in ("grain", "animation"):          # film/stillimage: x265 kennt dazu keinen Tune -> keiner gesetzt
        a += ["-tune", cfg["tune"]]
    params = ["log-level=error"] + ([f"pools={pools}"] if pools else []) + ([cfg["extra"]] if cfg["extra"] else [])
    return a + ["-x265-params", ":".join(params)]


def audio_args(cfg: dict, info: dict) -> list[str]:
    auds = [x for x in info["streams"] if x["codec_type"] == "audio"]
    if cfg["audio"] == "copy" or not auds:
        return ["-c:a", "copy"]
    a: list[str] = []
    for i, st in enumerate(auds):
        ch = int(st.get("channels") or 2)
        if cfg["audio"] == "aac":
            if ch > 6:
                a += [f"-ac:a:{i}", "6"]
            a += [f"-c:a:{i}", "aac", f"-b:a:{i}", "160k" if ch <= 2 else "256k"]
            layout = {1: "mono", 2: "stereo", 6: "5.1"}.get(min(ch, 6))
            if layout:
                a += [f"-filter:a:{i}", f"aformat=channel_layouts={layout}"]
        elif cfg["audio"] == "opus":
            layout = {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}.get(ch)
            a += [f"-c:a:{i}", "libopus", f"-b:a:{i}", "128k" if ch <= 2 else "320k" if ch <= 6 else "448k"]
            if layout:
                a += [f"-filter:a:{i}", f"aformat=channel_layouts={layout}"]
        else:
            if ch > 6:
                a += [f"-ac:a:{i}", "6"]
            a += [f"-c:a:{i}", cfg["audio"], f"-b:a:{i}", "192k" if ch <= 2 else "640k"]
    return a


def ffmpeg_args(src: Path, out: Path, cfg: dict, info: dict, crop) -> list[str]:
    a = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src), "-map", "0:v:0", "-map", "0:a?", "-map", "0:s?", "-map_chapters", "0"]
    if crop:
        a += ["-vf", crop]
    return a + x265_args(cfg) + ["-fps_mode", "cfr"] + audio_args(cfg, info) + ["-c:s", "copy", "-progress", "pipe:1", "-nostats", str(out)]


async def pump(proc, state: dict, key, tail: deque) -> int:
    """Liest die -progress-Ausgabe eines ffmpeg-Prozesses nach state[key] und sammelt die letzten Fehlerzeilen."""
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


async def aggregate(item: dict, state: dict, dur: float):
    """Fortschritt aller (Teil-)Prozesse zu einer Anzeige zusammenfassen."""
    t0 = time.monotonic()
    while True:
        if conv_state["paused"]:                      # Pausenzeit zählt nicht zur Laufzeit (Tempo/Restzeit)
            t0 += 0.8
            await asyncio.sleep(0.8)
            continue
        done = sum(s["t"] for s in state.values())
        el = max(1.0, time.monotonic() - t0)
        speed = done / el
        item.update(pct=max(0.0, min(0.97, done / dur)), fps=sum(s["fps"] for s in state.values()), speed=speed,
                    eta=max(0, (dur - done) / speed) if speed > 0.001 else 0, size_out=sum(s["size"] for s in state.values()))
        broadcast()
        await asyncio.sleep(0.8)


async def spawn(args: list[str]):
    return await asyncio.create_subprocess_exec("nice", "-n", "10", *args, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE, limit=2**20)


async def convert_single(item, src, cfg, info, dur, crop, out):
    proc = await spawn(ffmpeg_args(src, out, cfg, info, crop))
    conv_procs[item["id"]] = [proc]
    apply_pause([proc])
    state, tail = {0: {"t": 0.0, "fps": 0.0, "size": 0}}, deque(maxlen=12)
    agg = asyncio.create_task(aggregate(item, state, dur))
    try:
        rc = await pump(proc, state, 0, tail)
    finally:
        agg.cancel()
        conv_procs.pop(item["id"], None)
    if item["status"] == "skipped":
        out.unlink(missing_ok=True)
        raise SkipConversion()
    if rc != 0 or not out.exists():
        out.unlink(missing_ok=True)
        raise OSError("ffmpeg fehlgeschlagen: " + " | ".join(list(tail)[-4:]))


async def convert_segments(item, src, cfg, info, dur, crop, nseg, out):
    """Film in Zeitabschnitte teilen, parallel kodieren, danach mit Original-Audio/Untertiteln/Kapiteln zusammensetzen."""
    v = next(x for x in info["streams"] if x["codec_type"] == "video")
    num, den = (int(x) for x in v["r_frame_rate"].split("/"))
    fps = num / den
    total = round(dur * fps)
    bounds = [round(total * i / nseg) for i in range(nseg + 1)]
    work = CONV_WORK / f"{item['id']}-seg"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    pools = max(2, (os.cpu_count() or 4) // nseg)
    vf = (crop + "," if crop else "") + "setpts=PTS-STARTPTS"
    procs, tails, state = [], [], {}
    try:
        for i in range(nseg):
            a = ["ffmpeg", "-hide_banner", "-nostdin", "-y"]
            if i > 0:
                a += ["-ss", f"{(bounds[i] - 0.5) / fps:.6f}"]       # Schnitt auf halber Bildgrenze: eindeutig, ohne doppeltes/fehlendes Bild
            if i < nseg - 1:
                a += ["-to", f"{(bounds[i + 1] - 0.5) / fps:.6f}"]
            a += ["-i", str(src), "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", vf] + x265_args(cfg, pools) + \
                 ["-r", f"{num}/{den}", "-fps_mode", "cfr", "-progress", "pipe:1", "-nostats", str(work / f"seg{i:02d}.mkv")]
            procs.append(await spawn(a))
            tails.append(deque(maxlen=8))
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
                raise OSError(f"Segment {i + 1}/{nseg} fehlgeschlagen: " + " | ".join(list(tails[i])[-3:]))
        for i in range(nseg):                                        # jedes Segment muss die erwartete Länge haben
            want = (bounds[i + 1] - bounds[i]) / fps
            got = float((await probe(work / f"seg{i:02d}.mkv"))["format"]["duration"])
            if abs(got - want) > 2 / fps + 0.3:
                raise OSError(f"Segment {i + 1} hat falsche Länge ({got:.2f}s statt {want:.2f}s)")
        item.update(pct=0.98, eta=0, fps=0.0)
        broadcast()
        lst = work / "list.txt"
        lst.write_text("".join(f"file '{work}/seg{i:02d}.mkv'\n" for i in range(nseg)))
        mux = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(src),
               "-map", "0:v:0", "-map", "1:a?", "-map", "1:s?", "-map_chapters", "1", "-c:v", "copy"] + audio_args(cfg, info) + \
              ["-c:s", "copy", str(out)]
        p = await spawn(mux)
        conv_procs[item["id"]] = [p]
        apply_pause([p])
        _, err = await p.communicate()
        conv_procs.pop(item["id"], None)
        if item["status"] == "skipped":
            raise SkipConversion()
        if p.returncode != 0 or not out.exists():
            raise OSError("Zusammensetzen fehlgeschlagen: " + err.decode(errors="replace")[-300:])
        # Bildanzahl des Ergebnisses prüfen (±1 Bild je Schnittstelle toleriert)
        r = await asyncio.create_subprocess_exec("ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                                                 "stream=nb_read_packets", "-of", "csv=p=0", str(out),
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        o, _ = await r.communicate()
        frames = int(o.decode().strip().split(",")[0] or 0)
        if abs(frames - total) > nseg + 3:
            raise OSError(f"Bildanzahl stimmt nicht ({frames} statt ca. {total})")
    except BaseException:
        out.unlink(missing_ok=True)
        for pr in procs:
            if pr.returncode is None:
                pr.terminate()
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
