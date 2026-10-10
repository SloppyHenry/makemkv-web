"""Bibliothek: Angaben zu einer Datei (aus ffprobe), Einordnung, Prüfung gegen Konvertierungs-Einstellungen und Einsparungs-Schätzung."""
from app import convert_caps, convert_stats
from app.config import LIB_CODECS

INFO_VERSION = 3           # ältere Cache-Einträge ohne die neuen Felder werden neu geprüft
AUDIO_BPS = convert_stats.AUDIO_BPS


def _fps(v: dict) -> float:
    try:
        n, d = (int(x) for x in str(v.get("r_frame_rate", "0/1")).split("/"))
        return round(n / d, 3) if d else 0.0
    except ValueError:
        return 0.0


def lib_info(pr: dict) -> dict:
    v = next((x for x in pr["streams"] if x["codec_type"] == "video"), {})
    auds = [x for x in pr["streams"] if x["codec_type"] == "audio"]
    subs = [x for x in pr["streams"] if x["codec_type"] == "subtitle"]
    dur = float(pr["format"].get("duration") or 0)
    tr = v.get("color_transfer")
    ftags = {str(k).upper(): v for k, v in (pr["format"].get("tags") or {}).items()}

    def abps(a):
        name = str(a.get("codec_name", "")).lower()
        return int(a.get("bit_rate") or 0) or AUDIO_BPS.get(next((k for k in AUDIO_BPS if name.startswith(k)), ""), 448_000)
    return {"codec": v.get("codec_name", ""), "w": v.get("width", 0), "h": v.get("height", 0), "pix": v.get("pix_fmt", ""),
            "hdr": tr in ("smpte2084", "arib-std-b67"), "hdr_fmt": {"smpte2084": "HDR10", "arib-std-b67": "HLG"}.get(tr, ""),
            "dovi": any("DOVI" in str(x.get("side_data_type", "")) or "Dolby Vision" in str(x.get("side_data_type", "")) for x in v.get("side_data_list", [])),
            "dur": dur, "fps": _fps(v), "bitrate": int(pr["format"].get("bit_rate") or 0),
            "encoded": "MKW_CONVERTED" in ftags, "enc_note": ftags.get("MKW_CONVERTED", ""),
            "interlaced": v.get("field_order", "progressive") not in ("progressive", "unknown", ""), "profile": v.get("profile", ""),
            "audio": [f'{a.get("codec_name", "?")} {a.get("channels", "?")}ch {a.get("tags", {}).get("language", "")}'.strip() for a in auds],
            "alist": [{"codec": a.get("codec_name", "?"), "profile": a.get("profile", ""), "ch": a.get("channels", 0), "lang": a.get("tags", {}).get("language", ""),
                       "title": a.get("tags", {}).get("title", "")} for a in auds],
            "abytes": int(sum(abps(a) for a in auds) * dur / 8),
            "subs": len(subs), "slist": [{"codec": s.get("codec_name", "?"), "lang": s.get("tags", {}).get("language", ""), "forced": bool((s.get("disposition") or {}).get("forced"))} for s in subs],
            "chapters": len(pr.get("chapters") or []), "v": INFO_VERSION}


def lib_state(info) -> str:
    if info is None:
        return "unknown"
    if info["hdr"]:
        return "hdr"
    if info["codec"] == "hevc":
        return "hevc"
    return "ok" if info["codec"] in LIB_CODECS else "other"


def kind_of(info: dict) -> str:
    """'sd' | 'hd' | 'uhd' – bestimmt das Standard-Preset."""
    if info["h"] >= 1600 or info["w"] >= 3000:
        return "uhd"
    return "hd" if info["h"] >= 700 or info["w"] >= 1200 else "sd"


DISC_KIND = {"sd": "dvd", "hd": "bluray", "uhd": "uhd"}


def pseudo_probe(info: dict) -> dict:
    """Aus den gespeicherten Angaben ein ffprobe-ähnliches Ergebnis (für Prüfungen, die nur Codec/HDR/Spuren brauchen)."""
    st = [{"codec_type": "video", "codec_name": info["codec"], "width": info["w"], "height": info["h"], "color_transfer": "smpte2084" if info.get("hdr_fmt") == "HDR10" else
           "arib-std-b67" if info.get("hdr_fmt") == "HLG" else "", "r_frame_rate": f"{round((info.get('fps') or 24) * 1000)}/1000"}]
    st += [{"codec_type": "audio", "channels": a["ch"], "tags": {"language": a["lang"]}} for a in info.get("alist", [])]
    st += [{"codec_type": "subtitle", "tags": {"language": s["lang"]}, "disposition": {"forced": int(s["forced"])}} for s in info.get("slist", [])]
    return {"streams": st, "format": {"duration": str(info["dur"])}}


def file_issue(cfg: dict, info: dict | None, rel: str = "") -> str:
    """Warum diese Datei mit diesen Einstellungen nicht konvertiert werden soll ('' = in Ordnung)."""
    if rel and not rel.lower().endswith(".mkv"):
        return "nur MKV-Dateien lassen sich konvertieren"
    if info is None:
        return "nicht lesbar"
    pp = pseudo_probe(info)
    if why := convert_caps.unusable(cfg, pp):
        return why
    v, p, snd = cfg["video"], cfg["picture"], cfg["sound"]
    same_family = (info["codec"] == "hevc" and (v["codec"] == "x265" or v["hw"].startswith("hevc_"))) or (info["codec"] == "av1" and v["codec"] == "svtav1")
    changes = (p["scale"] != "keep" or p["denoise"] != "off" or p["deint"] != "off" or p["hdr"] == "tonemap" or snd["mode"] != "copy" or cfg["subs"]["mode"] != "all"
               or cfg["quality"]["mode"] != "crf")
    if same_family and not changes:
        return "ist bereits " + ("HEVC" if info["codec"] == "hevc" else "AV1")
    return ""


def default_cfg(info: dict) -> tuple[str, dict]:
    from app import convert_presets            # erst zur Laufzeit (lädt Einstellungen und Presets)
    d = convert_presets.default_for(DISC_KIND[kind_of(info)])
    return d["id"], d["cfg"]


def estimate(info: dict, size: int) -> dict:
    """Erwartete Größe nach der Konvertierung mit dem Standard-Preset dieser Disc-Art."""
    pid, cfg = default_cfg(info)
    src = {"size": size, "dur": info["dur"], "w": info["w"], "h": info["h"], "fps": info.get("fps") or 24.0, "audio": info["audio"], "abytes": info.get("abytes", 0)}
    b, n = convert_stats.estimate_size(cfg, src)
    return {"preset": pid, "bytes": min(b, size), "samples": n, "issue": file_issue(cfg, info)}
