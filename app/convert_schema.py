"""Conversion settings, schema v2: structure, validation, adoption of the old five fields (v1), compatibility with old machines.

v2 (nested, versioned):
  {"v": 2, "convert": bool, "origin": "<preset id or ''>",
   "video":   {"codec": x265|x264|svtav1|hw|copy, "hw": "<encoder when codec=hw>", "bits": 8|10, "speed": "...", "tune": "...", "extra": "..."},
   "quality": {"mode": crf|size|bitrate, "crf": <number, each codec has its own scale>, "size_gb": <number>, "kbps": <number>},
   "picture": {"scale": keep|1080|720|576|480, "crop": auto|off|manual, "crop_manual": "w:h:x:y", "deint": off|auto|on|ivtc,
               "denoise": off|light|medium, "hdr": keep|tonemap},
   "sound":   {"mode": copy|aac|opus|ac3|eac3, "channels": keep|51|stereo, "kbps": 0 = automatic},
   "subs":    {"mode": all|forced|langs|none, "langs": "eng,deu"}}
In addition, the old fields (rf, preset, tune, extra, audio; that is why the v2 sections are called "origin" and "sound") sit on top as a mirror, so that old interfaces and old machines
still read something sensible. Changing only the old fields also changes the new ones (see `clean_convert`).
"""
import copy
import re

from app.config import CONVERT_DEFAULT, X265_PRESETS

SCHEMA = 2
X264_PRESETS = X265_PRESETS
SVT_SPEEDS = [str(i) for i in range(13, -1, -1)]          # 13 = fast … 0 = slow
TUNES = ("none", "film", "grain", "animation", "stillimage")
HW_RE = re.compile(r"(h264|hevc|av1)_(vaapi|qsv|nvenc|videotoolbox)")
EXTRA_RE = re.compile(r"[A-Za-z0-9_=:.,\-]*")
LANGS_RE = re.compile(r"[a-z]{3}(,[a-z]{3})*")
CROP_RE = re.compile(r"\d{1,5}:\d{1,5}:\d{1,5}:\d{1,5}")

# Properties per codec. q = (worst, best) quality number (CRF/RF/QP): the "smaller ← → better" slider spans this range.
# The scales are chosen so that the same slider position gives roughly the same perceived quality (see docs/agents/status-paket-f.md).
# rel = relative computing time per level (medium = 1), bpp = bits per pixel relative to x265 at the same perceived quality.
CODECS = {
    "x265": {"label": "H.265 / HEVC (x265)", "encoder": "libx265", "unit": "RF", "q": (30, 14), "qlim": (8, 40), "speeds": list(X265_PRESETS),
             "speed_def": "slow", "rel": [.12, .2, .35, .5, .7, 1, 2.3, 5, 8], "bpp": 1.0, "hdr": True, "bits": (8, 10), "segments": True},
    "x264": {"label": "H.264 (x264)", "encoder": "libx264", "unit": "CRF", "q": (28, 12), "qlim": (8, 40), "speeds": list(X264_PRESETS),
             "speed_def": "slow", "rel": [.05, .08, .15, .25, .5, 1, 1.7, 3, 6], "bpp": 1.55, "hdr": False, "bits": (8, 10), "segments": True},
    "svtav1": {"label": "AV1 (SVT-AV1)", "encoder": "libsvtav1", "unit": "CRF", "q": (45, 18), "qlim": (8, 63), "speeds": SVT_SPEEDS,
               "speed_def": "6", "rel": [.04, .06, .1, .17, .3, .5, .8, 1.2, 2.2, 3.5, 6, 11, 25, 60], "bpp": 0.8, "hdr": False, "bits": (8, 10), "segments": True},
    "hw": {"label": "Hardware", "encoder": "", "unit": "QP", "q": (34, 16), "qlim": (8, 50), "speeds": [""], "speed_def": "", "rel": [.03],
           "bpp": 1.7, "hdr": True, "bits": (8, 10), "segments": False},
    "copy": {"label": "Remux only", "encoder": "", "unit": "", "q": (30, 14), "qlim": (8, 40), "speeds": [""], "speed_def": "", "rel": [0.01],
             "bpp": 1.0, "hdr": True, "bits": (8, 10), "segments": False},
}
AUDIO_MODES = ("copy", "aac", "opus", "ac3", "eac3")
DEFAULT_V2 = {
    "v": SCHEMA, "convert": False, "origin": "",
    "video": {"codec": "x265", "hw": "", "bits": 10, "speed": "slow", "tune": "none", "extra": CONVERT_DEFAULT["extra"]},
    "quality": {"mode": "crf", "crf": CONVERT_DEFAULT["rf"], "size_gb": 0.0, "kbps": 0},
    "picture": {"scale": "keep", "crop": "auto", "crop_manual": "", "deint": "off", "denoise": "off", "hdr": "keep"},
    "sound": {"mode": "copy", "channels": "keep", "kbps": 0},
    "subs": {"mode": "all", "langs": ""},
}


def default_v2() -> dict:
    return copy.deepcopy(DEFAULT_V2)


def crf_to_level(codec: str, crf: float) -> float:
    """Quality 0..100 (0 = small, 100 = best) for a codec quality number."""
    w, b = CODECS[codec if codec in CODECS else "x265"]["q"]
    return max(0.0, min(100.0, (w - float(crf)) / (w - b) * 100))


def level_to_crf(codec: str, level: float) -> int:
    w, b = CODECS[codec if codec in CODECS else "x265"]["q"]
    return round(w - (w - b) * max(0.0, min(100.0, float(level))) / 100)


def translate_quality(crf: float, src: str, dst: str) -> int:
    """The same perceived level in another codec (e.g. when switching in the editor)."""
    return level_to_crf(dst, crf_to_level(src, crf))


def _choice(v, allowed, default):
    return v if v in allowed else default


def _num(v, lo, hi, default, cast=float):
    try:
        return max(lo, min(hi, cast(v)))
    except (TypeError, ValueError):
        return default


LEGACY_KEYS = ("rf", "preset", "tune", "extra", "audio")


def _legacy_overlay(c: dict, d: dict) -> dict:
    """Apply the old fields (rf, preset, tune, extra, audio) where they differ from the mirror of the v2 state
    (so that an old interface that only knows these fields still has an effect)."""
    v, q, a = d["video"], d["quality"], d["sound"]
    m = legacy_mirror(d)
    x265 = v["codec"] == "x265"
    if x265 and "rf" in c and c["rf"] != m["rf"]:
        q["crf"] = _num(c["rf"], 14, 30, q["crf"], int)
    if x265 and c.get("preset") in X265_PRESETS and c["preset"] != m["preset"]:
        v["speed"] = c["preset"]
    if c.get("tune") in TUNES and c["tune"] != m["tune"]:
        v["tune"] = c["tune"]
    if x265 and "extra" in c and c["extra"] != m["extra"]:
        e = str(c["extra"]).strip()
        v["extra"] = e if EXTRA_RE.fullmatch(e) else CONVERT_DEFAULT["extra"]
    if c.get("audio") in AUDIO_MODES and c["audio"] != m["audio"]:
        a["mode"] = c["audio"]
    return d


def clean_v2(c: dict) -> dict:
    """Turn any input (v1 with five fields, v2, even half filled) into a complete, validated v2 dict."""
    c = c if isinstance(c, dict) else {}
    d = default_v2()
    d["convert"] = bool(c.get("convert", d["convert"]))
    if c.get("v") == SCHEMA or any(isinstance(c.get(k), dict) for k in ("video", "quality", "picture", "sound", "subs")):
        _fill_v2(c, d)
    if any(k in c for k in LEGACY_KEYS):
        _legacy_overlay(c, d)
    return finish(d)


def _fill_v2(c: dict, d: dict):
    pr = c.get("origin")
    d["origin"] = pr if isinstance(pr, str) and re.fullmatch(r"[\w\-]{1,40}", pr) and isinstance(c.get("video"), dict) else ""
    vi, qi, pi, ai, si = (c.get(k) if isinstance(c.get(k), dict) else {} for k in ("video", "quality", "picture", "sound", "subs"))
    v, q, p, a, s = d["video"], d["quality"], d["picture"], d["sound"], d["subs"]
    v["codec"] = _choice(vi.get("codec"), CODECS, v["codec"])
    cd = CODECS[v["codec"]]
    hw = vi.get("hw")
    v["hw"] = (hw if isinstance(hw, str) and HW_RE.fullmatch(hw) else "hevc_vaapi") if v["codec"] == "hw" else ""
    v["bits"] = 8 if (vi.get("bits") in (8, "8") or v["hw"].startswith("h264_")) else 10
    if v["codec"] in ("x265", "x264", "svtav1"):
        v["speed"] = _choice(str(vi.get("speed", "")), cd["speeds"], cd["speed_def"])
    else:
        v["speed"] = ""
    v["tune"] = _choice(vi.get("tune"), TUNES, "none")
    e = str(vi.get("extra", CONVERT_DEFAULT["extra"] if v["codec"] == "x265" and not vi else "")).strip()[:300]
    v["extra"] = e if EXTRA_RE.fullmatch(e) else ""
    q["mode"] = _choice(qi.get("mode"), ("crf", "size", "bitrate"), "crf")
    lo, hi = cd["qlim"]
    dflt = CONVERT_DEFAULT["rf"] if v["codec"] == "x265" else translate_quality(CONVERT_DEFAULT["rf"], "x265", v["codec"])
    q["crf"] = _num(qi.get("crf", dflt), lo, hi, dflt, int)
    q["size_gb"] = round(_num(qi.get("size_gb", 0), 0, 500, 0.0), 2)
    q["kbps"] = _num(qi.get("kbps", 0), 0, 100000, 0, int)
    if (q["mode"] == "size" and q["size_gb"] <= 0) or (q["mode"] == "bitrate" and q["kbps"] <= 0):
        q["mode"] = "crf"
    p["scale"] = _choice(str(pi.get("scale", "keep")), ("keep", "1080", "720", "576", "480"), "keep")
    p["crop"] = _choice(pi.get("crop"), ("auto", "off", "manual"), "auto")
    cm = str(pi.get("crop_manual", "")).strip()
    p["crop_manual"] = cm if CROP_RE.fullmatch(cm) else ""
    if p["crop"] == "manual" and not p["crop_manual"]:
        p["crop"] = "auto"
    p["deint"] = _choice(pi.get("deint"), ("off", "auto", "on", "ivtc"), "off")
    p["denoise"] = _choice(pi.get("denoise"), ("off", "light", "medium"), "off")
    p["hdr"] = _choice(pi.get("hdr"), ("keep", "tonemap"), "keep")
    a["mode"] = _choice(ai.get("mode"), AUDIO_MODES, "copy")
    a["channels"] = _choice(ai.get("channels"), ("keep", "51", "stereo"), "keep")
    a["kbps"] = _num(ai.get("kbps", 0), 0, 1536, 0, int) if a["mode"] != "copy" else 0
    s["mode"] = _choice(si.get("mode"), ("all", "forced", "langs", "none"), "all")
    ls = str(si.get("langs", "")).strip().lower().replace(" ", "")
    s["langs"] = ls if LANGS_RE.fullmatch(ls) else ""
    if s["mode"] == "langs" and not s["langs"]:
        s["mode"] = "all"


def finish(d: dict) -> dict:
    """Add the mirror of the old fields."""
    d.update(legacy_mirror(d))
    return d


def legacy_mirror(d: dict) -> dict:
    v, q, a = d["video"], d["quality"], d["sound"]
    x265 = v["codec"] == "x265"
    return {"rf": int(q["crf"]) if x265 and 14 <= q["crf"] <= 30 else CONVERT_DEFAULT["rf"],
            "preset": v["speed"] if x265 and v["speed"] in X265_PRESETS else CONVERT_DEFAULT["preset"],
            "tune": v["tune"] if v["tune"] in TUNES else "none",
            "extra": v["extra"] if x265 else CONVERT_DEFAULT["extra"],
            "audio": a["mode"]}


def is_v1_compatible(d: dict) -> bool:
    """Can an old machine (only x265 with five fields) run this job the same way? Otherwise it must not go there."""
    v, q, p, a, s = d["video"], d["quality"], d["picture"], d["sound"], d["subs"]
    return (v["codec"] == "x265" and v["bits"] == 10 and q["mode"] == "crf" and 14 <= q["crf"] <= 30
            and p == {"scale": "keep", "crop": "auto", "crop_manual": "", "deint": "off", "denoise": "off", "hdr": "keep"}
            and a["channels"] == "keep" and a["kbps"] == 0 and s["mode"] == "all" and a["mode"] in ("copy", "ac3", "eac3", "aac", "opus"))


def to_v1(d: dict) -> dict:
    """The five old fields (for old machines, only meaningful if `is_v1_compatible`)."""
    return {"convert": bool(d.get("convert", True)), **{k: legacy_mirror(d)[k] for k in ("rf", "preset", "tune", "extra", "audio")}}


AUDIO_NAMES = {"copy": "copy audio", "aac": "AAC", "opus": "Opus", "ac3": "AC3", "eac3": "E-AC3"}


def describe(d: dict) -> str:
    """Short description for the log and the interface."""
    v, q, p, a = d["video"], d["quality"], d["picture"], d["sound"]
    cd = CODECS[v["codec"]]
    if v["codec"] == "copy":
        vid = "copy video"
    else:
        name = v["hw"] if v["codec"] == "hw" else {"x265": "x265", "x264": "x264", "svtav1": "SVT-AV1"}[v["codec"]]
        qual = f"{cd['unit']} {q['crf']}" if q["mode"] == "crf" else (f"{q['size_gb']:g} GB" if q["mode"] == "size" else f"{q['kbps']} kb/s")
        vid = f"{name} {v['bits']}-bit · {qual}" + (f" · {v['speed']}" if v["speed"] else "")
    bits = [vid]
    if p["scale"] != "keep":
        bits.append(f"≤ {p['scale']}p")
    if p["deint"] != "off":
        bits.append("Deinterlace " + p["deint"])
    if p["denoise"] != "off":
        bits.append("denoise " + p["denoise"])
    bits.append(AUDIO_NAMES[a["mode"]] + (" stereo" if a["channels"] == "stereo" and a["mode"] != "copy" else ""))
    return " · ".join(bits)
