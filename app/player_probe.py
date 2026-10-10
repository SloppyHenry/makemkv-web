"""Player: Pfadprüfung, ffprobe-Auswertung und die Entscheidung Direkt / Remux / Transkodieren.

Reine Logik ohne Webanbindung (die Entscheidung `plan()` ist eine reine Funktion und lässt sich testen).
"""
import asyncio
import json
import time
from pathlib import Path

from fastapi import HTTPException

from app.files import inside_out

# Endungen, die der Player anfasst (ISO-Abbilder und Sperrdateien nicht)
VIDEO_EXT = (".mkv", ".mp4", ".m4v", ".mov", ".webm", ".m2ts", ".ts", ".mpg", ".mpeg", ".avi", ".wmv")
MIME = {".mkv": "video/x-matroska", ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}
TEXT_SUBS = ("subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text", "microdvd", "sami", "subviewer")
BITMAP_SUBS = ("hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub")
HDR_TRC = ("smpte2084", "arib-std-b67")

PROBE_TIMEOUT = 40
_cache: dict[tuple, tuple[float, dict]] = {}       # (Pfad, Größe, mtime) -> (Zeit, Auswertung)


def check_path(rel: str) -> Path:
    """Datei im Ausgabeordner prüfen: kein Ausbruch (inside_out), nur Videoendungen, keine Punktdateien (Sperrdateien), nur Dateien."""
    if not rel or "\x00" in rel:
        raise HTTPException(400, "Ungültiger Pfad")
    p = inside_out(rel)                                   # Pfadausbruch -> 400 (löst auch Symlinks auf)
    if any(part.startswith(".") for part in Path(rel).parts):
        raise HTTPException(400, "Ungültiger Pfad")
    if p.suffix.lower() == ".iso":
        raise HTTPException(415, ".iso-Abbilder lassen sich nicht abspielen. Rippe den Titel als MKV oder entpacke das Abbild.")
    if p.suffix.lower() not in VIDEO_EXT:
        raise HTTPException(415, "Dieses Dateiformat lässt sich nicht abspielen.")
    if not p.is_file():
        raise HTTPException(404, "Datei nicht gefunden")
    return p


async def run_ffprobe(p: Path) -> dict:
    proc = await asyncio.create_subprocess_exec(
        "nice", "-n", "5", "ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", "-show_chapters", f"file:{p}",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), PROBE_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        raise HTTPException(504, "Die Datei ließ sich nicht rechtzeitig lesen (Netzlaufwerk langsam?).")
    if proc.returncode:
        raise HTTPException(422, "Datei nicht lesbar: " + err.decode(errors="replace")[-200:].strip())
    return json.loads(out)


def _num(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _fps(s: str) -> float:
    try:
        a, _, b = s.partition("/")
        return round(float(a) / float(b or 1), 3)
    except (ValueError, ZeroDivisionError):
        return 0.0


def summarize(pr: dict) -> dict:
    """Aus der ffprobe-Ausgabe das machen, was Oberfläche und Entscheidung brauchen."""
    streams = pr.get("streams", [])
    fmt = pr.get("format", {})
    v = next((s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    video = None
    if v:
        pix = v.get("pix_fmt", "")
        video = {"codec": v.get("codec_name", ""), "profile": v.get("profile", ""), "pix_fmt": pix, "w": v.get("width", 0), "h": v.get("height", 0),
                 "bits": 10 if "10" in pix else 12 if "12" in pix else 8, "fps": _fps(v.get("avg_frame_rate", "0/1")),
                 "hdr": v.get("color_transfer") in HDR_TRC, "interlaced": v.get("field_order", "progressive") not in ("progressive", "unknown", ""),
                 "stream": v["index"]}
    audio, subs = [], []
    for s in streams:
        tags, disp = s.get("tags", {}), s.get("disposition", {})
        if s.get("codec_type") == "audio":
            audio.append({"i": len(audio), "stream": s["index"], "codec": s.get("codec_name", ""), "profile": s.get("profile", ""), "channels": s.get("channels", 0),
                          "layout": s.get("channel_layout", ""), "lang": tags.get("language", ""), "title": tags.get("title", ""), "default": bool(disp.get("default"))})
        elif s.get("codec_type") == "subtitle":
            codec = s.get("codec_name", "")
            subs.append({"i": len(subs), "stream": s["index"], "codec": codec, "lang": tags.get("language", ""), "title": tags.get("title", ""),
                         "forced": bool(disp.get("forced")), "default": bool(disp.get("default")),
                         "kind": "text" if codec in TEXT_SUBS else "bitmap" if codec in BITMAP_SUBS else "other"})
    chapters = [{"start": round(_num(c.get("start_time")), 3), "end": round(_num(c.get("end_time")), 3), "title": c.get("tags", {}).get("title", "")}
                for c in pr.get("chapters", [])]
    return {"duration": _num(fmt.get("duration")) or _num((v or {}).get("duration")), "container": fmt.get("format_name", ""), "size": int(_num(fmt.get("size"))),
            "bitrate": int(_num(fmt.get("bit_rate"))), "video": video, "audio": audio, "subs": subs, "chapters": chapters}


async def probe_file(p: Path) -> dict:
    """ffprobe mit kleinem Zwischenspeicher (Schlüssel: Pfad, Größe, Änderungszeit)."""
    st = p.stat()
    key = (str(p), st.st_size, int(st.st_mtime))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    info = summarize(await run_ffprobe(p))
    if len(_cache) > 64:
        _cache.pop(next(iter(_cache)))
    _cache[key] = (time.time(), info)
    return info


# ---------------------------------------------------------------- Entscheidung

def parse_caps(s) -> set[str]:
    """Fähigkeiten des Browsers als Wortliste, z. B. "mkv,h264,hevc,hevc10,aac,opus"."""
    if isinstance(s, (list, tuple, set)):
        s = ",".join(map(str, s))
    return {x.strip().lower() for x in str(s or "").split(",") if x.strip()}


def video_ok(v: dict, caps: set[str]) -> bool:
    """Kann der Browser dieses Video (im MP4) abspielen?"""
    c, bits = v["codec"], v["bits"]
    if c == "h264":
        return "h264" in caps and (bits == 8 or "h264_10" in caps)
    if c == "hevc":
        return "hevc" in caps and (bits == 8 or "hevc10" in caps)
    if c in ("vp9", "av1"):
        return c in caps and bits <= 10
    return False


AUDIO_COPY = {"aac": "aac", "mp3": "mp3", "opus": "opus", "flac": "flac", "vorbis": "vorbis"}


def audio_ok(a: dict, caps: set[str], mp4: bool = True) -> bool:
    """Kann der Browser diese Tonspur unverändert abspielen (AAC/MP3 immer, Opus/FLAC nur wenn gemeldet; AC3/DTS/TrueHD nie)?"""
    c = a["codec"]
    if c in ("aac", "mp3"):
        return a["channels"] <= 6
    if c in ("opus", "flac"):
        return c in caps
    if c in ("ac3", "eac3"):
        return c in caps
    return False


def pick_audio(info: dict, audio: int | None) -> dict | None:
    """Gewählte Tonspur (Ordnungszahl), sonst die als Standard markierte, sonst die erste."""
    a = info["audio"]
    if not a:
        return None
    if audio is not None and 0 <= audio < len(a):
        return a[audio]
    return next((x for x in a if x["default"]), a[0])


def plan(info: dict, caps: set[str], audio: int | None = None, burn: int | None = None, force: str = "auto",
         transcode_allowed: bool = True, ext: str = ".mkv") -> dict:
    """Wie wird abgespielt? -> {mode: direct|remux|transcode, video: copy|x264, audio: copy|aac|none, burn, reasons[], ok, error}.
    `force`: auto | remux | transcode (Nutzerwahl, remux fällt auf Transkodierung zurück, wenn das Video es nicht kann)."""
    v = info["video"]
    out = {"mode": "remux", "video": "copy", "audio": "none", "burn": None, "reasons": [], "ok": True, "error": ""}
    if not v:
        return {**out, "ok": False, "error": "Die Datei enthält kein Video."}
    a = pick_audio(info, audio)
    default_a = pick_audio(info, None)
    reasons = out["reasons"]
    vok = video_ok(v, caps)
    if not vok:
        reasons.append(f"Der Browser kann {_vname(v)} nicht abspielen.")
    if v["hdr"] and not vok:
        reasons.append("HDR wird für die Wiedergabe auf SDR umgerechnet.")
    bsub = next((s for s in info["subs"] if s["i"] == burn and s["kind"] == "bitmap"), None) if burn is not None else None
    if burn is not None and not bsub:
        out["burn"] = None
    if bsub:
        out["burn"] = bsub["i"]
        reasons.append("Bilduntertitel werden ins Video eingebrannt.")
    transcode = (not vok) or bool(bsub) or force == "transcode"
    if force == "transcode" and vok and not bsub:
        reasons.append("Auf Wunsch umgewandelt (kleiner, ruckelfrei).")
    if transcode and not transcode_allowed:
        return {**out, "ok": False, "error": "Umwandeln ist in den Einstellungen ausgeschaltet; diese Datei lässt sich so nicht abspielen."}
    out["video"] = "x264" if transcode else "copy"
    # direkt: nur wenn der Browser Container, Video und die Standardtonspur kann und nichts umgewandelt werden muss
    container_ok = ext in (".mp4", ".m4v", ".mov", ".webm") or (ext == ".mkv" and "mkv" in caps)
    if not transcode and force != "remux" and container_ok and (a is None or (audio_ok(a, caps) and a is default_a)):
        return {**out, "mode": "direct", "audio": "copy" if a else "none"}
    if a is None:
        out["audio"] = "none"
    elif audio_ok(a, caps) and a["codec"] in ("aac", "mp3", "ac3", "eac3"):      # nur das geht unverändert in fragmentiertes MP4
        out["audio"] = "copy"
    else:
        out["audio"] = "aac"
        reasons.append(f"Ton ({_aname(a)}) wird in AAC umgewandelt.")
    if transcode:
        out["mode"] = "transcode"
        return out
    if ext not in (".mp4", ".m4v", ".mov", ".webm") and not ("mkv" in caps and ext == ".mkv"):
        reasons.append("Der Container wird neu verpackt (Remux).")
    out["mode"] = "remux"
    return out


def _vname(v: dict) -> str:
    n = {"mpeg2video": "MPEG-2", "vc1": "VC-1", "h264": "H.264", "hevc": "HEVC", "mpeg4": "MPEG-4", "wmv3": "WMV", "vp9": "VP9", "av1": "AV1"}.get(v["codec"], v["codec"].upper())
    return f"{n} {v['bits']}-bit" if v["bits"] > 8 else n


def _aname(a: dict) -> str:
    n = {"ac3": "AC3", "eac3": "E-AC3", "dts": "DTS", "truehd": "TrueHD", "flac": "FLAC", "opus": "Opus", "pcm_s16le": "PCM", "pcm_dvd": "PCM"}.get(a["codec"], a["codec"].upper())
    if a["codec"] == "dts" and "MA" in (a.get("profile") or ""):
        n = "DTS-HD MA"
    return n
