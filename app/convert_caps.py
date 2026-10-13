"""Capabilities of this machine (encoders, filters, hardware) and the check of who may run a job.

On startup ffmpeg is queried (`-encoders`, `-filters`) and every hardware encoder is tested with a tiny trial run (device present and
working?). The result is reported via `ext.register_capability`: `encoders` (list) and `convert` (schema, codecs, hardware, filters, speed).
Old machines (without these fields) only get jobs they understand the same way (schema v1, see convert_schema.is_v1_compatible).
"""
import asyncio
import os
import platform
import re

from app import ext
from app.convert_schema import CODECS, HW_RE, SCHEMA, is_v1_compatible
from app.ffmpeg_args import HW_DEVICE, hdr_problem, is_hdr

caps: dict = {"probed": False, "encoders": set(), "filters": set(), "hw": [], "hw10": [], "x264_10": True}
SW = {"x265": "libx265", "x264": "libx264", "svtav1": "libsvtav1"}


async def _ff(args: list[str], timeout: float = 25.0) -> tuple[int, str]:
    try:
        p = await asyncio.create_subprocess_exec("ffmpeg", "-hide_banner", "-nostdin", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(p.communicate(), timeout)
        return p.returncode or 0, out.decode(errors="replace")
    except (OSError, asyncio.TimeoutError):
        return 1, ""


def _device_present(fam: str) -> bool:
    if fam in ("vaapi", "qsv"):
        return os.path.exists(HW_DEVICE)
    if fam == "nvenc":
        return os.path.exists("/dev/nvidiactl") or os.path.exists("/dev/nvidia0")
    return fam == "videotoolbox" and platform.system() == "Darwin"


async def _hw_test(enc: str, ten: bool) -> bool:
    """Encode a few frames with the hardware encoder – only what works is reported."""
    fam = enc.split("_", 1)[1]
    fmt = "p010le" if ten else "nv12"
    pre = ["-vaapi_device", HW_DEVICE] if fam == "vaapi" else []
    vf = f"format={fmt}" + (",hwupload" if fam == "vaapi" else "")
    rc, _ = await _ff(pre + ["-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=5", "-frames:v", "5", "-vf", vf, "-c:v", enc, "-f", "null", "-"])
    return rc == 0


async def probe_capabilities():
    _, enc = await _ff(["-encoders"])
    names = set(re.findall(r"^\s*[VAS][A-Z.]{5}\s+(\S+)", enc, re.M))
    _, flt = await _ff(["-filters"])
    filters = set(re.findall(r"^\s*[T.][S.][C.]?\s+(\S+)\s", flt, re.M)) | set(re.findall(r"^\s*\S{2,3}\s+(\w+)\s+\S+->\S+", flt, re.M))
    hw, hw10 = [], []
    for e in sorted(n for n in names if HW_RE.fullmatch(n)):
        if _device_present(e.split("_", 1)[1]) and await _hw_test(e, False):
            hw.append(e)
            if not e.startswith("h264_") and await _hw_test(e, True):
                hw10.append(e)
    x264_10 = True
    if "libx264" in names:
        rc, _ = await _ff(["-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=128x72:rate=5", "-frames:v", "3", "-pix_fmt", "yuv420p10le", "-c:v", "libx264", "-f", "null", "-"])
        x264_10 = rc == 0
    caps.update(probed=True, encoders=names, filters=filters, hw=hw, hw10=hw10, x264_10=x264_10)
    publish()


def codecs_available() -> list[str]:
    out = [k for k, e in SW.items() if (e in caps["encoders"] if caps["probed"] else k == "x265")]
    return out + (["hw"] if caps["hw"] else []) + ["copy"]


def public_caps(speed: dict | None = None) -> dict:
    usable = sorted([e for e in caps["encoders"] if e in SW.values() or e in ("libopus", "aac", "ac3", "eac3")] + caps["hw"])
    return {"encoders": usable, "convert": {"schema": SCHEMA, "codecs": codecs_available(), "hw": list(caps["hw"]), "hw10": list(caps["hw10"]),
            "filters": sorted(caps["filters"] & {"bwdif", "yadif", "fieldmatch", "decimate", "hqdn3d", "zscale", "tonemap", "idet", "cropdetect"}),
            "audio": [m for m, e in (("aac", "aac"), ("opus", "libopus"), ("ac3", "ac3"), ("eac3", "eac3")) if not caps["probed"] or e in caps["encoders"]],
            "cores": os.cpu_count() or 1, "speed": speed or {}}}


def publish():
    from app import convert_stats                          # only at runtime (stats does not import this module)
    c = public_caps(convert_stats.speed_table())
    ext.register_capability("encoders", c["encoders"])
    ext.register_capability("convert", c["convert"])


def unusable(cfg: dict, info: dict) -> str:
    """Why this machine cannot run the job ('' = it can). Without a completed probe only the obvious is checked."""
    v, s = cfg["video"], cfg["sound"]
    if caps["probed"]:
        if v["codec"] in SW and SW[v["codec"]] not in caps["encoders"]:
            return f"{CODECS[v['codec']]['label']} is not installed on this machine"
        if v["codec"] == "x264" and v["bits"] == 10 and not caps["x264_10"]:
            return "x264 only supports 8 bit here"
        if v["codec"] == "hw":
            if v["hw"] not in caps["hw"]:
                return f"Hardware encoder {v['hw']} is not available on this machine"
            if v["bits"] == 10 and not v["hw"].startswith("h264_") and v["hw"] not in caps["hw10"]:
                return f"{v['hw']} cannot do 10 bit here"
        need = {"opus": "libopus", "aac": "aac", "ac3": "ac3", "eac3": "eac3"}.get(s["mode"])
        if need and need not in caps["encoders"]:
            return f"Audio format {s['mode']} is not available here"
        miss = [f for f in _filters_needed(cfg, info) if f not in caps["filters"]]
        if miss:
            return "The machine lacks the ffmpeg filter " + ", ".join(miss)
    return hdr_problem(cfg, info)


def _filters_needed(cfg: dict, info: dict) -> list[str]:
    p = cfg["picture"]
    need = {"auto": ["idet", "bwdif"], "on": ["bwdif"], "ivtc": ["fieldmatch", "yadif", "decimate"]}.get(p["deint"], [])
    if p["denoise"] != "off":
        need.append("hqdn3d")
    if p["hdr"] == "tonemap" and is_hdr(info):
        need += ["zscale", "tonemap"]
    return need


def peer_ok(cfg: dict, peer: dict) -> tuple[bool, str]:
    """May this other machine get the job? Old machines only with jobs they understand as before."""
    if not peer.get("reachable"):
        return False, "not reachable"
    legacy = peer.get("legacy") or not (peer.get("capabilities") or {})
    if is_v1_compatible(cfg):
        return (True, "") if not legacy or peer.get("has_handover", True) else (False, "still runs a version without hand-over")
    c = (peer.get("capabilities") or {}).get("convert")
    if legacy or not isinstance(c, dict) or int(c.get("schema") or 0) < SCHEMA:
        return False, "older version: does not understand the new conversion settings (only x265 with the previous options)"
    v = cfg["video"]
    if v["codec"] == "hw":
        if v["hw"] not in (c.get("hw") or []):
            return False, f"reports no hardware encoder {v['hw']}"
        if v["bits"] == 10 and not v["hw"].startswith("h264_") and v["hw"] not in (c.get("hw10") or []):
            return False, f"{v['hw']} cannot do 10 bit there"
    elif v["codec"] not in (c.get("codecs") or []):
        return False, f"{CODECS[v['codec']]['label']} is not installed there"
    p, a = cfg["picture"], cfg["sound"]
    flt = set(c.get("filters") or [])
    miss = [f for f in {"auto": ["idet", "bwdif"], "on": ["bwdif"], "ivtc": ["fieldmatch", "yadif", "decimate"]}.get(p["deint"], [])
            + (["hqdn3d"] if p["denoise"] != "off" else []) + (["zscale", "tonemap"] if p["hdr"] == "tonemap" else []) if f not in flt]
    if miss:
        return False, "the ffmpeg filter is missing there: " + ", ".join(miss)
    if a["mode"] != "copy" and a["mode"] not in (c.get("audio") or []):
        return False, f"audio format {a['mode']} not available there"
    return True, ""
