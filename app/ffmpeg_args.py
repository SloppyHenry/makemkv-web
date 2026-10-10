"""ffmpeg-Argumente aus Konvertierungs-Einstellungen (Schema v2, siehe convert_schema.py): Filter, Video je Codec, Ton, Untertitel, Durchgänge.

Alles hier sind reine Funktionen (kein Prozessstart), damit sie ohne ffmpeg getestet werden können.
`ctx` bündelt, was erst beim Konvertieren feststeht:
  info   Ergebnis von ffprobe (Quelle)          crop   "crop=w:h:x:y" oder None (automatisch erkannt)
  scan   "progressive" | "interlaced" | "telecine" (für Deinterlace „automatisch“)
  hdr    {"master": "...", "cll": "...", "dovi": bool} aus den Bilddaten der Quelle
  pools  Rechenkerne für diesen Prozess (0 = Encoder entscheidet)      dur  Länge der Quelle in Sekunden
  kbps   Ziel-Videobitrate bei Zielgröße/Bitrate (0 = Qualitätsmodus)  passes (1 oder 2)  passlog  Pfad der Zwei-Durchgang-Datei
"""
import os
import shlex

from app.config import X265_PRESETS
from app.convert_schema import describe

HW_DEVICE = os.environ.get("HW_DEVICE", "/dev/dri/renderD128")
HDR_TRANSFERS = ("smpte2084", "arib-std-b67")
HQDN3D = {"light": "hqdn3d=2:1:2:3", "medium": "hqdn3d=3:2:2:3"}        # Stufen wie bei HandBrake (Weak/Medium)
TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
           "zscale=t=bt709:m=bt709:r=tv")
SAMPLE_INFO = {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "r_frame_rate": "24000/1001"},
                           {"codec_type": "audio", "channels": 6}, {"codec_type": "subtitle"}], "format": {"duration": "7200"}}


def mark(cfg: dict) -> str:
    """Kennzeichnung im Container: Diese Datei wurde von MakeMKV-Web konvertiert (die Bibliothek zeigt sie dann als „konvertiert“)."""
    return "MKW_CONVERTED=" + describe(cfg)[:150]


def vstream(info: dict) -> dict:
    return next((x for x in info["streams"] if x["codec_type"] == "video"), {})


def is_hdr(info: dict) -> bool:
    return vstream(info).get("color_transfer") in HDR_TRANSFERS


def hw_family(cfg: dict) -> str:
    return cfg["video"]["hw"].split("_", 1)[1] if cfg["video"]["codec"] == "hw" else ""


def hdr_kept(cfg: dict, info: dict) -> bool:
    return is_hdr(info) and cfg["picture"]["hdr"] == "keep" and cfg["video"]["codec"] in ("x265", "hw", "copy")


def hdr_problem(cfg: dict, info: dict) -> str:
    """Warum diese Einstellung für HDR-Material nicht geeignet ist ('' = in Ordnung)."""
    v = cfg["video"]
    if not is_hdr(info) or cfg["picture"]["hdr"] != "keep" or v["codec"] == "copy":
        return ""
    if v["codec"] in ("x264", "svtav1") or (v["codec"] == "hw" and not v["hw"].startswith("hevc_")):
        return "HDR geht bei diesem Codec verloren – HEVC wählen oder HDR nach SDR umrechnen"
    if v["bits"] != 10:
        return "HDR braucht 10 Bit"
    return ""


# ---------------------------------------------------------------- Bildfilter
def deint_filter(cfg: dict, ctx: dict) -> str:
    d = cfg["picture"]["deint"]
    scan = ctx.get("scan", "progressive")
    if d == "off" or (d == "auto" and scan == "progressive"):
        return ""
    if d == "ivtc" or (d == "auto" and scan == "telecine"):
        return "fieldmatch=order=auto:combmatch=full,yadif=mode=send_frame:parity=auto:deint=interlaced,decimate"
    return "bwdif=mode=send_frame:parity=auto:deint=" + ("all" if d == "on" else "interlaced")


def changes_framecount(cfg: dict, ctx: dict) -> bool:
    return "decimate" in deint_filter(cfg, ctx)


def filter_chain(cfg: dict, ctx: dict, last: str = "") -> list[str]:
    """Filter in dieser Reihenfolge: Zeilensprung, Zuschneiden, Entrauschen, Skalieren, HDR→SDR, Formatwandlung für Hardware."""
    p, v, info = cfg["picture"], cfg["video"], ctx["info"]
    f = [deint_filter(cfg, ctx)]
    if p["crop"] == "manual":
        f.append("crop=" + p["crop_manual"])
    elif p["crop"] == "auto" and ctx.get("crop"):
        f.append(ctx["crop"])
    f.append(HQDN3D.get(p["denoise"], ""))
    if p["scale"] != "keep":
        f.append(f"scale=w=-2:h=min(ih\\,{p['scale']}):flags=lanczos")        # nie hochskalieren
    if p["hdr"] == "tonemap" and is_hdr(info):
        f.append(TONEMAP)
    fam = hw_family(cfg)
    bits = v["bits"] if not (p["hdr"] == "tonemap" and is_hdr(info)) else 10
    if v["codec"] == "hw":
        f.append("format=" + ("p010le" if bits == 10 else "nv12"))
        if fam == "vaapi":
            f.append("hwupload")
    elif p["hdr"] == "tonemap" and is_hdr(info):
        f.append("format=" + ("yuv420p10le" if bits == 10 else "yuv420p"))
    if last:
        f.append(last)
    return [x for x in f if x]


# ---------------------------------------------------------------- Video
def pix_fmt(cfg: dict) -> str:
    return "yuv420p10le" if cfg["video"]["bits"] == 10 else "yuv420p"


def _color_params(info: dict) -> list[str]:
    s = vstream(info)
    return [f"colorprim={s.get('color_primaries', 'bt2020')}", f"transfer={s.get('color_transfer')}", f"colormatrix={s.get('color_space', 'bt2020nc')}"]


def _rate(ctx: dict) -> list[str]:
    return ["-b:v", f"{int(ctx['kbps'])}k"]


def x265_args(cfg: dict, ctx: dict) -> list[str]:
    v, q = cfg["video"], cfg["quality"]
    a = ["-c:v", "libx265", "-preset", v["speed"]] + (_rate(ctx) if ctx.get("kbps") else ["-crf", str(q["crf"])]) + ["-pix_fmt", pix_fmt(cfg)]
    if v["tune"] in ("grain", "animation"):          # film/stillimage: x265 kennt dazu keinen Tune -> keiner gesetzt
        a += ["-tune", v["tune"]]
    params = ["log-level=error"] + ([f"pools={ctx['pools']}"] if ctx.get("pools") else [])
    if hdr_kept(cfg, ctx["info"]) and cfg["video"]["codec"] == "x265":
        params += _color_params(ctx["info"]) + ["repeat-headers=1"]
        if vstream(ctx["info"]).get("color_transfer") == "smpte2084":
            params += ["hdr10=1", "hdr10-opt=1"] + ([f"master-display={ctx['hdr']['master']}"] if ctx.get("hdr", {}).get("master") else []) \
                + ([f"max-cll={ctx['hdr']['cll']}"] if ctx.get("hdr", {}).get("cll") else [])
    if ctx.get("passes") and ctx.get("pass_no"):
        params += [f"pass={ctx['pass_no']}", f"stats={ctx['passlog']}.x265.log"]
    if v["extra"]:
        params.append(v["extra"])
    return a + ["-x265-params", ":".join(params)]


def x264_args(cfg: dict, ctx: dict) -> list[str]:
    v, q = cfg["video"], cfg["quality"]
    a = ["-c:v", "libx264", "-preset", v["speed"]] + (_rate(ctx) if ctx.get("kbps") else ["-crf", str(q["crf"])]) + ["-pix_fmt", pix_fmt(cfg)]
    if v["tune"] != "none":
        a += ["-tune", v["tune"]]
    if ctx.get("pools"):
        a += ["-threads", str(ctx["pools"])]
    if ctx.get("passes") and ctx.get("pass_no"):
        a += ["-pass", str(ctx["pass_no"]), "-passlogfile", ctx["passlog"]]
    return a + (["-x264-params", v["extra"]] if v["extra"] else [])


def svtav1_args(cfg: dict, ctx: dict) -> list[str]:
    v, q = cfg["video"], cfg["quality"]
    a = ["-c:v", "libsvtav1", "-preset", v["speed"]] + (_rate(ctx) if ctx.get("kbps") else ["-crf", str(q["crf"])]) + ["-pix_fmt", pix_fmt(cfg)]
    params = ["tune=0"] + ([f"lp={ctx['pools']}"] if ctx.get("pools") else [])
    if v["tune"] == "grain":
        params.append("film-grain=8")             # Korn wird beim Abspielen nachgebildet statt Bits dafür auszugeben
    if v["extra"]:
        params.append(v["extra"])
    return a + ["-svtav1-params", ":".join(params)]


def hw_args(cfg: dict, ctx: dict) -> list[str]:
    enc, q = cfg["video"]["hw"], cfg["quality"]["crf"]
    fam = hw_family(cfg)
    a = ["-c:v", enc]
    if ctx.get("kbps"):
        a += ["-b:v", f"{int(ctx['kbps'])}k"]
    elif fam == "vaapi":
        a += ["-rc_mode", "CQP", "-qp", str(q)]
    elif fam == "qsv":
        a += ["-global_quality", str(q), "-preset", "slow"]
    elif fam == "nvenc":
        a += ["-rc", "vbr", "-cq", str(q), "-b:v", "0", "-preset", "p5"]
    else:                                         # videotoolbox: 0..100, höher = besser
        a += ["-q:v", str(max(1, min(100, round(85 - (q - 16) * 2.5))))]
    if enc.startswith("hevc_") and fam == "videotoolbox":
        a += ["-tag:v", "hvc1"]
    if hdr_kept(cfg, ctx["info"]):
        s = vstream(ctx["info"])
        a += ["-color_primaries", s.get("color_primaries", "bt2020"), "-color_trc", s.get("color_transfer"), "-colorspace", s.get("color_space", "bt2020nc")]
    return a


def global_args(cfg: dict) -> list[str]:
    """Vor „-i“: Hardware-Gerät anlegen."""
    return ["-vaapi_device", HW_DEVICE] if hw_family(cfg) == "vaapi" else []


def video_args(cfg: dict, ctx: dict) -> list[str]:
    c = cfg["video"]["codec"]
    if c == "copy":
        return ["-c:v", "copy"]
    return {"x265": x265_args, "x264": x264_args, "svtav1": svtav1_args, "hw": hw_args}[c](cfg, ctx)


# ---------------------------------------------------------------- Ton
def audio_args(cfg: dict, info: dict) -> list[str]:
    snd = cfg["sound"]
    auds = [x for x in info["streams"] if x["codec_type"] == "audio"]
    mode = snd["mode"]
    if mode == "copy" or not auds:
        return ["-c:a", "copy"]
    a: list[str] = []
    for i, st in enumerate(auds):
        src = int(st.get("channels") or 2)
        ch = {"keep": src, "51": min(src, 6), "stereo": min(src, 2)}[snd["channels"]]
        ch = min(ch, 8 if mode == "opus" else 6)             # AAC/AC3/E-AC3 im ffmpeg bis 5.1, Opus bis 7.1
        if ch != src:
            a += [f"-ac:a:{i}", str(ch)]
        kb = snd["kbps"]
        if mode == "aac":
            a += [f"-c:a:{i}", "aac", f"-b:a:{i}", f"{kb or (160 if ch <= 2 else 256)}k"]
            layout = {1: "mono", 2: "stereo", 6: "5.1"}.get(ch)
        elif mode == "opus":
            a += [f"-c:a:{i}", "libopus", f"-b:a:{i}", f"{kb or (128 if ch <= 2 else 320 if ch <= 6 else 448)}k"]
            layout = {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}.get(ch)
        else:
            a += [f"-c:a:{i}", mode, f"-b:a:{i}", f"{kb or (192 if ch <= 2 else 640)}k"]
            layout = None
        if layout:
            a += [f"-filter:a:{i}", f"aformat=channel_layouts={layout}"]
    return a


# ---------------------------------------------------------------- Untertitel
def sub_streams(cfg: dict, info: dict) -> list[int]:
    """Nummern (innerhalb der Untertitelspuren) der Spuren, die behalten werden."""
    subs = [x for x in info["streams"] if x["codec_type"] == "subtitle"]
    s = cfg["subs"]
    if s["mode"] == "none":
        return []
    if s["mode"] == "forced":
        return [i for i, x in enumerate(subs) if (x.get("disposition") or {}).get("forced")]
    if s["mode"] == "langs":
        keep = set(s["langs"].split(","))
        return [i for i, x in enumerate(subs) if (x.get("tags") or {}).get("language", "und") in keep | {"und", ""}]
    return list(range(len(subs)))


def sub_maps(cfg: dict, info: dict, input_no: int = 0) -> list[str]:
    if cfg["subs"]["mode"] == "all":
        return ["-map", f"{input_no}:s?"]
    out: list[str] = []
    for i in sub_streams(cfg, info):
        out += ["-map", f"{input_no}:s:{i}"]
    return out


# ---------------------------------------------------------------- Zielgröße / Bitrate
def target_kbps(cfg: dict, info: dict, dur: float) -> int:
    """Videobitrate (kb/s) für den Modus „Zielgröße“ bzw. „Bitrate“; 0 im Qualitätsmodus."""
    q = cfg["quality"]
    if q["mode"] == "bitrate":
        return q["kbps"]
    if q["mode"] != "size" or dur <= 0:
        return 0
    n_aud = sum(1 for x in info["streams"] if x["codec_type"] == "audio")
    if cfg["sound"]["mode"] == "copy":
        aud = sum(int(x.get("bit_rate") or 0) or 640_000 for x in info["streams"] if x["codec_type"] == "audio")
    else:
        aud = n_aud * (cfg["sound"]["kbps"] or 192) * 1000
    total = q["size_gb"] * 1024 ** 3 * 0.985 * 8 / dur
    return max(100, int((total - aud) / 1000))


def two_pass(cfg: dict) -> bool:
    return cfg["video"]["codec"] in ("x265", "x264") and cfg["quality"]["mode"] != "crf"


# ---------------------------------------------------------------- Gesamtbefehl
def ffmpeg_args(src, out, cfg: dict, ctx: dict, pass_no: int = 0) -> list[str]:
    """Befehl für einen Prozess (ganzer Film). pass_no 1 = nur Analyse (Ton/Untertitel aus, Ausgabe verworfen), 2 = Ergebnis, 0 = ein Durchgang."""
    info, v = ctx["info"], cfg["video"]
    c = {**ctx, "pass_no": pass_no, "passes": two_pass(cfg)}
    a = ["ffmpeg", "-hide_banner", "-nostdin", "-y"] + global_args(cfg) + ["-i", str(src), "-map", "0:v:0"]
    if pass_no != 1:
        a += ["-map", "0:a?"] + sub_maps(cfg, info) + ["-map_chapters", "0"]
    fl = filter_chain(cfg, c) if v["codec"] != "copy" else []
    if fl:
        a += ["-vf", ",".join(fl)]
    a += video_args(cfg, c)
    if v["codec"] != "copy":
        a += ["-fps_mode", "cfr"]
    if pass_no == 1:
        return a + ["-an", "-sn", "-progress", "pipe:1", "-nostats", "-f", "null", os.devnull]
    return a + audio_args(cfg, info) + ["-c:s", "copy", "-metadata", mark(cfg), "-progress", "pipe:1", "-nostats", str(out)]


def segment_args(src, part, cfg: dict, ctx: dict, seek: list[str], rate: str) -> list[str]:
    """Befehl für ein Zeitsegment (nur Bild, Ton/Untertitel kommen beim Zusammensetzen vom Original)."""
    fl = filter_chain(cfg, ctx, "setpts=PTS-STARTPTS")
    return ["ffmpeg", "-hide_banner", "-nostdin", "-y"] + seek + ["-i", str(src), "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", ",".join(fl)] \
        + video_args(cfg, ctx) + ["-r", rate, "-fps_mode", "cfr", "-progress", "pipe:1", "-nostats", str(part)]


def mux_args(list_file, src, out, cfg: dict, info: dict) -> list[str]:
    return ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-i", str(src), "-map", "0:v:0", "-map", "1:a?"] \
        + sub_maps(cfg, info, 1) + ["-map_chapters", "1", "-c:v", "copy"] + audio_args(cfg, info) + ["-c:s", "copy", "-metadata", mark(cfg), str(out)]


def command_preview(cfg: dict, info: dict | None = None, ctx_extra: dict | None = None) -> str:
    """Lesbarer Befehl für die Anzeige im Editor („Experten“). Automatisch Ermitteltes (Zuschneiden, Zeilensprung) steht als Platzhalter."""
    info = info or SAMPLE_INFO
    dur = float(info["format"].get("duration") or 0)
    ctx = {"info": info, "crop": "crop=1920:800:0:140" if cfg["picture"]["crop"] == "auto" else None, "scan": "interlaced",
           "hdr": {}, "pools": 0, "kbps": target_kbps(cfg, info, dur), "passlog": "/tmp/ffpass", **(ctx_extra or {})}
    passes = [1, 2] if two_pass(cfg) else [0]
    return "\n".join(" ".join(shlex.quote(x) for x in ffmpeg_args("Eingang.mkv", "Ausgang.mkv", cfg, ctx, p)) for p in passes)


__all__ = ["ffmpeg_args", "segment_args", "mux_args", "command_preview", "X265_PRESETS"]
