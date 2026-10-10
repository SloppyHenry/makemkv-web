"""Statistik bisheriger Konvertierungen (DATA/conv_stats.json) und Vorhersage von Zielgröße und Dauer.

Das Modell rechnet zuerst mit Faustwerten (Bits je Pixel je Codec, Bilder je Sekunde je Kern) und wird mit jeder fertigen Konvertierung
genauer: Größe über das Verhältnis „tatsächlich / Modell“, Tempo über die gemessene Geschwindigkeit je Kern, jeweils als Median.
"""
import json
import math
import os
import statistics
import time

from app.config import DATA, INSTANCE
from app.convert_schema import CODECS, crf_to_level, level_to_crf

STATS = DATA / "conv_stats.json"
MAX_RECORDS = 400
records: list[dict] = []
FPS_PER_CORE = {"x265": 0.95, "x264": 3.5, "svtav1": 1.2}       # Bilder/s je Kern bei 1080p und „relativer Zeit 1“ (x265 medium, x264 medium, SVT-AV1 ca. Preset 6)
HW_FPS = 70.0
REF_PX = 1920 * 1080
AUDIO_BPS = {"truehd": 4_000_000, "dts": 1_500_000, "flac": 1_000_000, "ac3": 448_000, "eac3": 640_000, "aac": 192_000, "mp3": 192_000, "opus": 128_000}


def load():
    try:
        records[:] = json.loads(STATS.read_text())[-MAX_RECORDS:]
    except (OSError, ValueError):
        records.clear()


def save():
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        STATS.write_text(json.dumps(records[-MAX_RECORDS:]))
    except OSError:
        pass


def family(cfg: dict) -> str:
    v = cfg["video"]
    return v["hw"] if v["codec"] == "hw" else v["codec"]


def out_px(w: int, h: int, scale: str) -> int:
    if scale != "keep" and h > int(scale):
        w, h = w * int(scale) / h, int(scale)
    return int(w * h)


def rel_time(cfg: dict) -> float:
    v = cfg["video"]
    cd = CODECS[v["codec"]]
    i = cd["speeds"].index(v["speed"]) if v["speed"] in cd["speeds"] else 0
    return cd["rel"][min(i, len(cd["rel"]) - 1)]


def audio_bytes(audio: list, dur: float) -> int:
    """Grobe Größe der Tonspuren aus Codecnamen (lib_info liefert 'codec Kanäle Sprache')."""
    tot = 0
    for a in audio:
        name = str(a).split()[0].lower() if a else ""
        tot += AUDIO_BPS.get(next((k for k in AUDIO_BPS if name.startswith(k)), ""), 448_000)
    return int(tot * dur / 8)


def model_bytes(cfg: dict, src: dict) -> int:
    """Erwartete Größe des Ergebnisses ohne Statistik. src: size, dur, w, h, fps, audio (Liste), abytes (optional)."""
    v, q = cfg["video"], cfg["quality"]
    dur = max(1.0, float(src.get("dur") or 1))
    abytes = src.get("abytes") or audio_bytes(src.get("audio") or [], dur)
    if v["codec"] == "copy":
        vid = max(0, src["size"] - abytes)
    elif q["mode"] == "size":
        return int(q["size_gb"] * 1024 ** 3)
    elif q["mode"] == "bitrate":
        vid = q["kbps"] * 1000 * dur / 8
    else:
        eq = level_to_crf("x265", crf_to_level(v["codec"], q["crf"]))
        bpp = 0.09 * CODECS[v["codec"]]["bpp"] * 2 ** ((20 - eq) / 6)
        bpp *= {"grain": 1.35, "animation": 0.8}.get(v["tune"], 1) * {"light": 0.93, "medium": 0.85}.get(cfg["picture"]["denoise"], 1)
        bpp *= 1 - 0.025 * math.log2(rel_time(cfg))          # jede Stufe langsamer spart etwas Platz
        px = out_px(int(src.get("w") or 1920), int(src.get("h") or 1080), cfg["picture"]["scale"])
        vid = min(px * float(src.get("fps") or 24) * bpp * dur / 8, max(0, src["size"] - abytes) * 0.85)
    return int(vid + audio_out_bytes(cfg, src, abytes, dur))


def audio_out_bytes(cfg: dict, src: dict, abytes: int = 0, dur: float = 0) -> int:
    """Größe der Tonspuren im Ergebnis."""
    snd = cfg["sound"]
    dur = dur or max(1.0, float(src.get("dur") or 1))
    abytes = abytes or src.get("abytes") or audio_bytes(src.get("audio") or [], dur)
    if snd["mode"] == "copy":
        return int(abytes)
    n = max(1, len(src.get("audio") or [1]))
    return int(n * dur * (snd["kbps"] or (128 if snd["channels"] == "stereo" else 256)) * 1000 / 8)


def _cal(cfg: dict) -> tuple[float, int]:
    fam = family(cfg)
    rs = [r for r in records if r.get("family") == fam and r.get("model")][-20:]
    if len(rs) < 2:
        return 1.0, len(rs)
    return max(0.4, min(2.5, statistics.median(r["size_out"] / r["model"] for r in rs))), len(rs)


def estimate_size(cfg: dict, src: dict) -> tuple[int, int]:
    """(Bytes, Zahl der Konvertierungen, auf denen die Schätzung beruht)."""
    cal, n = _cal(cfg)
    return int(model_bytes(cfg, src) * cal), n


def per_core(fam: str, node: str = "") -> tuple[float, int]:
    """Gemessenes Tempo je Kern (Bilder/s bei 1080p, relativer Zeit 1). Zuerst von diesem Rechner, sonst von allen, sonst Faustwert."""
    rs = [r for r in records if r.get("family") == fam and r.get("norm")]
    mine = [r["norm"] for r in rs if r["node"] == (node or INSTANCE)]
    use = mine or [r["norm"] for r in rs]
    if len(use) >= 1:
        return statistics.median(use[-12:]), len(use)
    return (HW_FPS if fam.startswith(("hevc_", "h264_", "av1_")) else FPS_PER_CORE.get(fam, 1.0)), 0


def speed_table() -> dict:
    """Tempo je Kern je Codec (nur gemessene Werte) für `capabilities.convert.speed`; andere Rechner rechnen damit ihre Vorhersage."""
    out = {}
    for fam in {r.get("family") for r in records if r.get("norm") and r.get("node") == INSTANCE}:
        out[fam] = round(per_core(fam, INSTANCE)[0], 3)
    return out


def estimate_secs(cfg: dict, src: dict, cores: int, node: str = "", speed: dict | None = None) -> tuple[float, int]:
    """(Sekunden, Zahl der Messungen) für einen Rechner mit `cores` Kernen. `speed` = von dort gemeldetes Tempo je Kern."""
    if cfg["video"]["codec"] == "copy":
        return max(1.0, src["size"] / 150e6), 0
    fam = family(cfg)
    base, n = per_core(fam, node)
    if speed and fam in speed and (n == 0 or node != INSTANCE):
        base, n = speed[fam], 1
    frames = float(src.get("dur") or 0) * float(src.get("fps") or 24)
    px = out_px(int(src.get("w") or 1920), int(src.get("h") or 1080), cfg["picture"]["scale"])
    hw = fam.startswith(("hevc_", "h264_", "av1_"))
    fps = base if hw else base * max(1.0, cores) ** 0.95 / rel_time(cfg)
    fps *= REF_PX / max(px, 1) if not hw else 1
    fac = (1.7 if cfg["quality"]["mode"] != "crf" and cfg["video"]["codec"] in ("x265", "x264") else 1.0) * (1.4 if cfg["picture"]["hdr"] == "tonemap" else 1.0)
    return frames / max(fps, 0.01) * fac, n


def record(item: dict):
    """Eine fertige Konvertierung festhalten (aufgerufen vom Worker)."""
    cfg, meta = item.get("cfg"), item.get("meta")
    if not cfg or not meta or not item.get("started") or not item.get("size_out"):
        return
    secs = max(1.0, time.time() - item["started"])
    src = {"size": item["size_in"], "dur": meta["dur"], "w": meta["w"], "h": meta["h"], "fps": meta["fps"], "audio": item.get("audio") or []}
    px = out_px(meta["w"], meta["h"], cfg["picture"]["scale"])
    fam = family(cfg)
    frames = meta["dur"] * meta["fps"]
    cores = os.cpu_count() or 1
    norm = 0.0
    if cfg["video"]["codec"] != "copy" and frames:
        eff = frames / secs
        norm = eff * rel_time(cfg) * px / REF_PX / (max(1, cores) ** 0.95) if not fam.startswith(("hevc_", "h264_", "av1_")) else eff
    records.append({"t": int(time.time()), "node": INSTANCE, "cores": cores, "family": fam, "speed": cfg["video"]["speed"], "crf": cfg["quality"]["crf"],
                    "mode": cfg["quality"]["mode"], "w": meta["w"], "h": meta["h"], "dur": meta["dur"], "size_in": item["size_in"], "size_out": item["size_out"],
                    "secs": round(secs, 1), "nseg": meta.get("nseg", 1), "norm": round(norm, 4), "model": model_bytes(cfg, src), "origin": item.get("origin", "")})
    del records[:-MAX_RECORDS]
    save()
    try:
        from app import convert_caps
        convert_caps.publish()
    except Exception:  # noqa: BLE001      Statistik darf die Konvertierung nie stören
        pass


def summary() -> dict:
    return {"count": len(records), "saved": sum(max(0, r["size_in"] - r["size_out"]) for r in records), "per_core": speed_table()}
