"""Player: path checks, ffprobe evaluation and the decision direct / remux / transcode.

Pure logic without a web layer (the decision `plan()` is a pure function and can be tested).
"""
import asyncio
import json
import time
from pathlib import Path

from fastapi import HTTPException

from app.files import inside_out

# extensions the player touches (not ISO images and lock files)
VIDEO_EXT = (".mkv", ".mp4", ".m4v", ".mov", ".webm", ".m2ts", ".ts", ".mpg", ".mpeg", ".avi", ".wmv")
MIME = {".mkv": "video/x-matroska", ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}
TEXT_SUBS = ("subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text", "microdvd", "sami", "subviewer")
BITMAP_SUBS = ("hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub")
HDR_TRC = ("smpte2084", "arib-std-b67")

PROBE_TIMEOUT = 40
_cache: dict[tuple, tuple[float, dict]] = {}       # (path, size, mtime) -> (time, evaluation)


def check_path(rel: str) -> Path:
    """Check a file in the output folder: no escape (inside_out), only video extensions, no dot files (lock files), only files."""
    if not rel or "\x00" in rel:
        raise HTTPException(400, "Invalid path")
    p = inside_out(rel)                                   # path escape -> 400 (also resolves symlinks)
    if any(part.startswith(".") for part in Path(rel).parts):
        raise HTTPException(400, "Invalid path")
    if p.suffix.lower() == ".iso":
        raise HTTPException(415, ".iso images cannot be played. Rip the title as MKV or extract the image.")
    if p.suffix.lower() not in VIDEO_EXT:
        raise HTTPException(415, "This file format cannot be played.")
    if not p.is_file():
        raise HTTPException(404, "File not found")
    return p


async def run_ffprobe(p: Path) -> dict:
    proc = await asyncio.create_subprocess_exec(
        "nice", "-n", "5", "ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", "-show_chapters", f"file:{p}",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), PROBE_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        raise HTTPException(504, "The file could not be read in time (slow network drive?).")
    if proc.returncode:
        raise HTTPException(422, "File not readable: " + err.decode(errors="replace")[-200:].strip())
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
    """Turn the ffprobe output into what the interface and the decision need."""
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
    """ffprobe with a small cache (key: path, size, modification time)."""
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


# ---------------------------------------------------------------- decision

def parse_caps(s) -> set[str]:
    """The browser's capabilities as a word list, e.g. "mkv,h264,hevc,hevc10,aac,opus"."""
    if isinstance(s, (list, tuple, set)):
        s = ",".join(map(str, s))
    return {x.strip().lower() for x in str(s or "").split(",") if x.strip()}


def video_ok(v: dict, caps: set[str]) -> bool:
    """Can the browser play this video (in MP4)?"""
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
    """Can the browser play this audio track unchanged (AAC/MP3 always, Opus/FLAC only if reported; AC3/DTS/TrueHD never)?"""
    c = a["codec"]
    if c in ("aac", "mp3"):
        return a["channels"] <= 6
    if c in ("opus", "flac"):
        return c in caps
    if c in ("ac3", "eac3"):
        return c in caps
    return False


LANG_ALIAS = {"de": "deu", "ger": "deu", "en": "eng", "fr": "fra", "fre": "fra", "es": "spa", "it": "ita", "nl": "nld", "dut": "nld", "pt": "por", "ru": "rus",
              "ja": "jpn", "zh": "zho", "chi": "zho", "ko": "kor", "pl": "pol", "cs": "ces", "cze": "ces", "tr": "tur", "sv": "swe", "da": "dan", "no": "nor",
              "fi": "fin", "el": "ell", "gre": "ell", "hu": "hun", "ar": "ara", "he": "heb"}


def lang_list(s) -> list[str]:
    """Language setting ("de, eng") as a list of three-letter codes in order of preference."""
    out = []
    for x in str(s or "").replace(";", ",").replace(" ", ",").split(","):
        x = x.strip().lower()
        if x:
            out.append(LANG_ALIAS.get(x, x))
    return out


def preferred_tracks(info: dict, audio_langs, sub_langs) -> tuple[int | None, int | None]:
    """Default for audio and subtitles: the first matching language of the preference list, otherwise the file's default
    (audio: marked as default, otherwise the first track; subtitles: text track marked as default/forced, otherwise none).
    Subtitles are text tracks only (image tracks are not supported); with the same language the non-forced one wins."""
    ai = None
    if info["audio"]:
        for lg in lang_list(audio_langs):
            hit = next((x for x in info["audio"] if LANG_ALIAS.get(x["lang"].lower(), x["lang"].lower()) == lg), None)
            if hit:
                ai = hit["i"]
                break
        if ai is None:
            ai = next((x["i"] for x in info["audio"] if x["default"]), info["audio"][0]["i"])
    texts = [x for x in info["subs"] if x["kind"] == "text"]
    si = None
    for lg in lang_list(sub_langs):
        cand = [x for x in texts if LANG_ALIAS.get(x["lang"].lower(), x["lang"].lower()) == lg]
        cand.sort(key=lambda x: x["forced"])
        if cand:
            si = cand[0]["i"]
            break
    if si is None and not lang_list(sub_langs):
        si = next((x["i"] for x in texts if x["default"] or x["forced"]), None)
    return ai, si


def pick_audio(info: dict, audio: int | None, pref: int | None = None) -> dict | None:
    """The chosen audio track (ordinal), otherwise the preferred one (`pref`), otherwise the one marked default, otherwise the first."""
    a = info["audio"]
    if not a:
        return None
    for i in (audio, pref):
        if i is not None and 0 <= i < len(a):
            return a[i]
    return next((x for x in a if x["default"]), a[0])


def plan(info: dict, caps: set[str], audio: int | None = None, force: str = "auto", transcode_allowed: bool = True, ext: str = ".mkv",
         pref_audio: int | None = None) -> dict:
    """How is it played? -> {mode: direct|remux|transcode, video: copy|x264, audio: copy|aac|none, reasons[], ok, error}.
    Transcoding (x264) only happens when the browser cannot play the video. `force`: auto | remux (no direct playback).
    `pref_audio`: preferred audio track (language setting); only it may be played directly, other tracks go via remux."""
    v = info["video"]
    out = {"mode": "remux", "video": "copy", "audio": "none", "reasons": [], "ok": True, "error": ""}
    if not v:
        return {**out, "ok": False, "error": "The file contains no video."}
    a = pick_audio(info, audio, pref_audio)
    default_a = pick_audio(info, None, pref_audio)
    reasons = out["reasons"]
    vok = video_ok(v, caps)
    if not vok:
        reasons.append(f"The browser cannot play {_vname(v)}.")
        if v["hdr"]:
            reasons.append("HDR is converted to SDR for playback.")
    transcode = not vok
    if transcode and not transcode_allowed:
        return {**out, "ok": False, "error": "Transcoding is switched off in the settings; this file cannot be played that way."}
    out["video"] = "x264" if transcode else "copy"
    # direct: only if the browser can handle the container, the video and the preferred audio track and nothing has to be converted
    container_ok = ext in (".mp4", ".m4v", ".mov", ".webm") or (ext == ".mkv" and "mkv" in caps)
    if not transcode and force != "remux" and container_ok and (a is None or (audio_ok(a, caps) and a is default_a)):
        return {**out, "mode": "direct", "audio": "copy" if a else "none"}
    if a is None:
        out["audio"] = "none"
    elif audio_ok(a, caps) and a["codec"] in ("aac", "mp3", "ac3", "eac3"):      # only these go into fragmented MP4 unchanged
        out["audio"] = "copy"
    else:
        out["audio"] = "aac"
        reasons.append(f"Audio ({_aname(a)}) is converted to AAC.")
    if transcode:
        out["mode"] = "transcode"
        return out
    if ext not in (".mp4", ".m4v", ".mov", ".webm") and not ("mkv" in caps and ext == ".mkv"):
        reasons.append("The container is repackaged (remux).")
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
