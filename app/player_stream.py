"""Player: ffmpeg-Ströme als fragmentiertes MP4, Sitzungen, Aufräumen und Untertitel (WebVTT).

Ein Strom = ein ffmpeg-Prozess. Er endet, wenn die Verbindung abreißt, der Player ihn beendet oder der Wächter ihn abräumt.
Suchen heißt: neue Sitzung mit anderem Startpunkt (ffmpeg-Neustart mit -ss).
"""
import asyncio
import hashlib
import json
import os
import secrets
import signal
import time
from collections import deque
from pathlib import Path

from fastapi import HTTPException
from starlette.responses import StreamingResponse

from app import state
from app.config import DATA, LOCK_TTL
from app.files import busy_reason, lock_path

MAX_STREAMS = 6             # gleichzeitige Ströme (Remux ist billig, Transkodieren zählt extra)
MAX_TRANSCODES = 1          # höchstens ein Transkodier-Strom je Rechner
IDLE_KILL = 300             # Sekunden ohne abgenommene Daten (Pause mit vollem Puffer), danach wird ffmpeg beendet
NEVER_FETCHED = 30          # Sitzung, deren Strom nie abgeholt wurde, verfällt
START_TIMEOUT = 60          # Sekunden bis zum ersten Byte (kalter Netzlaufwerk-Zugriff)
sessions: dict[str, dict] = {}
SUBDIR = DATA / "player-cache"


# ---------------------------------------------------------------- Rücksicht auf die eigentliche Arbeit

def busy_info() -> dict:
    """Läuft hier gerade ein Rip, eine Konvertierung oder Übertragung? (Der Player hält sich dann zurück.)"""
    rip = any(d.job for d in state.drives.values())
    conv = sum(1 for c in state.conversions if c["status"] == "running")
    up = any(u["status"] in state.ACTIVE for u in state.uploads)
    try:
        load = round(os.getloadavg()[0], 2)
    except OSError:
        load = 0.0
    return {"rip": rip, "convert": conv, "upload": up, "busy": rip or conv > 0 or up, "load": load, "cores": os.cpu_count() or 1}


def lock_info(rel: str, p: Path) -> dict | None:
    """Wird die Datei gerade konvertiert/übertragen oder ist sie gesperrt? (Abspielen bleibt erlaubt, die Oberfläche warnt.)"""
    reason = busy_reason(rel, False, p)
    by = ""
    try:
        lp = lock_path(p)
        if time.time() - lp.stat().st_mtime < LOCK_TTL:
            by = json.loads(lp.read_text()).get("inst", "andere Instanz")
            reason = reason or "wird gerade konvertiert"
    except (OSError, ValueError):
        pass
    return {"by": by, "reason": reason} if reason else None


# ---------------------------------------------------------------- Startpunkt (Keyframe) bei Video-Kopie

async def keyframe_before(p: Path, t: float) -> float:
    """Letzter Keyframe des Videos bis einschließlich t. Bei Video-Kopie muss ffmpeg genau dort einsetzen, sonst sind Bild und Ton verschoben."""
    if t <= 0.5:
        return 0.0
    for window in (30.0, 150.0):
        lo = max(0.0, t - window)
        proc = await asyncio.create_subprocess_exec(
            "nice", "-n", "5", "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time,flags", "-of", "csv=p=0",
            "-read_intervals", f"{lo:.3f}%{t + 0.5:.3f}", f"file:{p}", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), 20)
        except asyncio.TimeoutError:
            proc.kill()
            return t
        best = None
        for line in out.decode(errors="replace").splitlines():
            ts, _, flags = line.partition(",")
            try:
                v = float(ts)
            except ValueError:
                continue
            if "K" in flags and v <= t + 0.001:
                best = v if best is None else max(best, v)
        if best is not None:
            return best
        if lo == 0:
            break
    return 0.0 if t < 30 else t


# ---------------------------------------------------------------- ffmpeg-Aufruf

def video_filters(info: dict, plan: dict, max_h: int, tonemap: bool) -> str:
    v = info["video"]
    f = []
    if v["interlaced"]:
        f.append("yadif=deint=interlaced")
    if v["hdr"] and tonemap:
        f.append("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv")
    if max_h:                                           # 0 = Original, nicht verkleinern
        f.append(f"scale=-2:min({int(max_h)}\\,ih):flags=bilinear")
    f.append("format=yuv420p")
    return ",".join(f)


def build_args(p: Path, start: float, info: dict, plan: dict, audio_i: int | None, cfg: dict, threads: int, tonemap: bool) -> list[str]:
    a = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-fflags", "+genpts"]
    if start > 0:
        a += ["-ss", f"{start:.3f}"]
    a += ["-i", f"file:{p}"]
    trans = plan["video"] == "x264"
    a += ["-map", "0:v:0"]
    if trans:
        a += ["-vf", video_filters(info, plan, cfg["max_height"], tonemap)]
    if plan["audio"] != "none" and info["audio"]:
        a += ["-map", f"0:a:{audio_i if audio_i is not None else 0}"]
    if trans:
        a += ["-c:v", "libx264", "-preset", cfg["preset"], "-crf", str(cfg["crf"]), "-profile:v", "high", "-pix_fmt", "yuv420p",
              "-g", "48", "-sc_threshold", "0", "-threads", str(threads)]
    else:
        a += ["-c:v", "copy"]
        if info["video"]["codec"] == "hevc":
            a += ["-tag:v", "hvc1"]
    if plan["audio"] == "aac":
        a += ["-c:a", "aac", "-b:a", "192k", "-ac", "2"]
    elif plan["audio"] == "copy":
        a += ["-c:a", "copy"]
    a += ["-sn", "-dn", "-map_chapters", "-1", "-map_metadata", "-1", "-avoid_negative_ts", "make_zero", "-max_muxing_queue_size", "1024",
          "-movflags", "+frag_keyframe+empty_moov+default_base_moof", "-f", "mp4", "pipe:1"]
    return a


def pick_resources(plan: dict) -> tuple[int, int]:
    """(nice, Threads): Läuft Rip/Konvertierung/Übertragung, bekommt der Player nur wenig und die niedrigste Priorität."""
    cores = os.cpu_count() or 1
    if plan["video"] != "x264":
        return 10, 1
    if busy_info()["busy"]:
        return 19, 2 if cores > 2 else 1
    return 10, max(2, cores // 2)


# ---------------------------------------------------------------- Sitzungen

async def kill(s: dict):
    """ffmpeg sofort beenden (SIGKILL: am Strom ist nichts abzuschließen, und ein per SIGTERM angehaltener ffmpeg hängt bei vollem Pipe-Puffer)."""
    pr = s.get("proc")
    if not pr or pr.returncode is not None:
        return
    try:
        os.killpg(pr.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return
    try:
        await asyncio.wait_for(pr.wait(), 3)
    except asyncio.TimeoutError:
        pass


def alive(s: dict) -> bool:
    """Zählt für die Grenzen: noch nicht abgeholt (reserviert) oder ffmpeg läuft."""
    return s["proc"] is None or s["proc"].returncode is None


def drop_client(client: str):
    """Alle Sitzungen dieses Browsers beenden (neuer Strom ersetzt den alten, Schließen, Seitenwechsel)."""
    for sid, s in list(sessions.items()):
        if client and s["client"] == client:
            sessions.pop(sid, None)
            asyncio.create_task(kill(s))


def new_session(client: str, rel: str, p: Path, start: float, info: dict, plan: dict, audio_i: int | None, cfg: dict, tonemap: bool) -> dict:
    """Sitzung anlegen (ohne Prozess; der startet erst, wenn der Browser den Strom abholt). Prüft die Grenzen und ersetzt den alten Strom desselben Browsers."""
    client = client or secrets.token_hex(4)
    drop_client(client)
    if plan["video"] == "x264":
        if sum(1 for x in sessions.values() if x["plan"]["video"] == "x264" and alive(x)) >= MAX_TRANSCODES:      # eigener Strom wurde oben schon entfernt
            raise HTTPException(409, "Auf diesem Rechner läuft schon eine Umwandlung (anderer Browser). Bitte später noch einmal versuchen oder auf einem anderen Rechner abspielen.")
    if sum(1 for x in sessions.values() if alive(x)) >= MAX_STREAMS:
        raise HTTPException(409, "Auf diesem Rechner laufen schon zu viele Wiedergaben gleichzeitig.")
    sid = secrets.token_urlsafe(9)
    nice, threads = pick_resources(plan)
    s = {"id": sid, "client": client, "rel": rel, "path": p, "start": start, "plan": plan, "created": time.time(), "last_io": time.time(), "bytes": 0,
         "proc": None, "err": deque(maxlen=20), "nice": nice, "threads": threads,
         "args": build_args(p, start, info, plan, audio_i, cfg, threads, tonemap)}
    sessions[sid] = s
    return s


async def start_process(s: dict) -> bytes:
    """ffmpeg starten und das erste Datenstück abwarten (Fehler kommen so noch vor den HTTP-Kopfzeilen). Ein zweiter Abruf ersetzt den ersten."""
    await kill(s)
    try:
        pr = await asyncio.create_subprocess_exec("nice", "-n", str(s["nice"]), *s["args"], stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                  start_new_session=True)
    except OSError as e:
        raise HTTPException(503, f"ffmpeg lässt sich nicht starten: {e}")
    s["proc"], s["last_io"], s["bytes"] = pr, time.time(), 0

    async def drain():
        async for line in pr.stderr:
            s["err"].append(line.decode(errors="replace").rstrip())
    s["drain"] = asyncio.create_task(drain())
    try:
        first = await asyncio.wait_for(pr.stdout.read(1 << 16), START_TIMEOUT)
    except asyncio.TimeoutError:
        await kill(s)
        raise HTTPException(504, "ffmpeg lieferte nichts (Netzlaufwerk langsam?).")
    if not first:
        await kill(s)
        await asyncio.sleep(0.05)
        raise HTTPException(500, "Wiedergabe nicht möglich: " + (" ".join(list(s["err"])[-3:]) or "ffmpeg wurde ohne Ausgabe beendet."))
    s["bytes"] = len(first)
    return first


async def body(s: dict, first: bytes):
    pr = s["proc"]
    try:
        yield first
        s["last_io"] = time.time()
        while True:
            chunk = await pr.stdout.read(1 << 16)
            if not chunk:
                break
            s["bytes"] += len(chunk)
            yield chunk
            s["last_io"] = time.time()
    finally:                                           # Verbindung abgerissen, Ende oder Abbruch: ffmpeg sofort beenden
        await kill(s)


class StreamResponse(StreamingResponse):
    """MP4-Strom, der ffmpeg garantiert beendet, sobald die Antwort endet oder der Browser die Verbindung kappt
    (ohne das schließt Starlette den Erzeuger erst beim Aufräumen des Speichers, also viel zu spät)."""

    def __init__(self, s: dict, first: bytes):
        super().__init__(body(s, first), media_type="video/mp4", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "Accept-Ranges": "none"})
        self.sess = s

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            await kill(self.sess)
            try:
                await self.body_iterator.aclose()
            except Exception:  # noqa: BLE001
                pass


async def sweep():
    """Ein Durchgang des Wächters: verwaiste Sitzungen und festhängende ffmpeg-Prozesse abräumen."""
    now = time.time()
    for sid, s in list(sessions.items()):
        pr = s["proc"]
        if pr is None:
            if now - s["created"] > NEVER_FETCHED:
                sessions.pop(sid, None)
        elif pr.returncode is not None:
            if now - s["last_io"] > 60:
                sessions.pop(sid, None)
        elif now - s["last_io"] > IDLE_KILL:
            await kill(s)
            sessions.pop(sid, None)


async def janitor():
    while True:
        await asyncio.sleep(5)
        try:
            await sweep()
        except Exception as e:  # noqa: BLE001
            print(f"Player-Wächter: {e}", flush=True)


async def stop_all():
    for s in list(sessions.values()):
        await kill(s)
    sessions.clear()


def public_sessions() -> list:
    return [{"id": s["id"], "path": s["rel"], "mode": s["plan"]["mode"], "start": s["start"], "client": s["client"], "bytes": s["bytes"],
             "running": bool(s["proc"] and s["proc"].returncode is None), "pid": s["proc"].pid if s["proc"] else 0} for s in sessions.values()]


# ---------------------------------------------------------------- Untertitel (Textspuren -> WebVTT, zwischengespeichert)

_sub_tasks: dict[str, asyncio.Task] = {}
_sub_gate = asyncio.Semaphore(1)       # nie zwei Extraktionen gleichzeitig (lesen die ganze Datei)


def sub_key(p: Path) -> str:
    st = p.stat()
    return hashlib.sha1(f"{p}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:20]


async def _extract_all(p: Path, info: dict, key: str):
    """Alle Textspuren in einem Durchgang herausziehen (die Datei wird nur einmal gelesen)."""
    texts = [s for s in info["subs"] if s["kind"] == "text"]
    if not texts:
        return
    SUBDIR.mkdir(parents=True, exist_ok=True)
    args = ["nice", "-n", "10", "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", f"file:{p}"]
    for s in texts:
        args += ["-map", f"0:s:{s['i']}", "-c:s", "webvtt", "-f", "webvtt", f"{SUBDIR / (key + '-' + str(s['i']) + '.part')}"]
    async with _sub_gate:
        pr = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE, start_new_session=True)
        try:
            _, err = await asyncio.wait_for(pr.communicate(), 1800)
        except asyncio.TimeoutError:
            pr.kill()
            raise HTTPException(504, "Untertitel konnten nicht rechtzeitig gelesen werden.")
    for s in texts:
        part = SUBDIR / f"{key}-{s['i']}.part"
        if part.exists():
            part.replace(SUBDIR / f"{key}-{s['i']}.vtt")
    if pr.returncode and not any((SUBDIR / f"{key}-{s['i']}.vtt").exists() for s in texts):
        raise HTTPException(500, "Untertitel nicht lesbar: " + err.decode(errors="replace")[-200:])


async def subtitle_vtt(p: Path, info: dict, idx: int) -> str:
    sub = next((s for s in info["subs"] if s["i"] == idx), None)
    if not sub:
        raise HTTPException(404, "Untertitelspur nicht gefunden")
    if sub["kind"] != "text":
        raise HTTPException(415, "Bilduntertitel lassen sich nicht als Text anzeigen (nur einbrennen).")
    key = sub_key(p)
    f = SUBDIR / f"{key}-{idx}.vtt"
    if not f.exists():
        t = _sub_tasks.get(key)
        if t is None or t.done():
            t = _sub_tasks[key] = asyncio.create_task(_extract_all(p, info, key))
        try:
            await asyncio.shield(t)
        finally:
            if t.done():
                _sub_tasks.pop(key, None)
    try:
        return f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        raise HTTPException(500, "Untertitel nicht lesbar.")


def prune_cache(max_files: int = 300):
    try:
        files = sorted(SUBDIR.glob("*"), key=lambda x: x.stat().st_mtime)
    except OSError:
        return
    for f in files[:-max_files] if len(files) > max_files else []:
        f.unlink(missing_ok=True)
    for f in files:
        if f.suffix == ".part" and time.time() - f.stat().st_mtime > 3600:
            f.unlink(missing_ok=True)
