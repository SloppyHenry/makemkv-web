"""Konvertierungs-Presets, Namensraum „convert“ der Einstellungen und die API /api/convert/… (Meta, Vorhersage, Prüfung, Start auf einem Rechner).

Wird von main.py automatisch geladen (OPTIONAL_MODULES). Eigene Presets des Nutzers liegen in `settings["convert"]["presets"]`,
die Zuordnung „welches Preset für welche Disc-Art“ in `settings["convert"]["default_for"]`. `conv_parallel`/`conv_segments` und die alten
Standard-Presets (`presets.bluray/dvd`, Schema v1 bzw. migriert) bleiben im Namensraum „general“; die Oberfläche speichert beides.
"""
import asyncio
import os
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from app import cluster, convert_caps, convert_probe, convert_stats, ext
from app.config import INSTANCE, PRESET_DEFAULTS
from app.convert import clean_convert
from app.convert_builtin import BUILTIN, BUILTIN_IDS, DEFAULT_FOR
from app.convert_schema import CODECS, SCHEMA, clean_v2, crf_to_level, describe, is_v1_compatible, level_to_crf, to_v1
from app.ffmpeg_args import command_preview
from app.state import broadcast, peers_state, settings

router = APIRouter(prefix="/api/convert")
ID_RE = re.compile(r"[a-z0-9][a-z0-9\-]{0,29}")


class ConvertSettings(BaseModel):
    presets: dict = {}          # eigene Presets: Kennung -> {name, desc, cfg}
    default_for: dict = {}      # "bluray" | "dvd" | "uhd" -> Preset-Kennung

    @field_validator("presets")
    @classmethod
    def _presets(cls, v):
        out = {}
        for pid, p in (v or {}).items():
            if ID_RE.fullmatch(str(pid)) and pid not in BUILTIN_IDS and isinstance(p, dict) and str(p.get("name", "")).strip():
                out[pid] = {"name": str(p["name"]).strip()[:60], "desc": str(p.get("desc", "")).strip()[:200], "cfg": {**clean_v2(p.get("cfg") or {}), "origin": pid}}
        return out

    @field_validator("default_for")
    @classmethod
    def _default_for(cls, v):
        return {k: str(x) for k, x in (v or {}).items() if k in DEFAULT_FOR and re.fullmatch(r"[a-z0-9\-]{1,30}", str(x))}


def conf() -> dict:
    return settings.get("convert") or {"presets": {}, "default_for": {}}


def all_presets() -> list[dict]:
    user = [{"id": pid, "name": p["name"], "desc": p.get("desc", ""), "builtin": False, "kind": "", "cfg": p["cfg"]} for pid, p in conf()["presets"].items()]
    return [{k: v for k, v in p.items() if k != "why"} for p in BUILTIN] + user


def find_preset(pid: str) -> dict | None:
    return next((p for p in all_presets() if p["id"] == pid), None)


def default_for(kind: str) -> dict:
    """Vorgabe für eine Disc-Art: {id, cfg}. Die alten flachen Standard-Presets (general.presets) gelten weiter: nur wenn sie der Wahl entsprechen, steht
    eine Kennung dabei, sonst ist es eine „eigene Vorgabe“ (id leer)."""
    pid = conf()["default_for"].get(kind) or DEFAULT_FOR.get(kind, "bluray")
    p = find_preset(pid) or find_preset(DEFAULT_FOR.get(kind, "bluray"))
    flat = (settings.get("presets") or {}).get(kind) if kind in PRESET_DEFAULTS else None
    if flat is None or kind not in PRESET_DEFAULTS:
        return {"id": p["id"], "cfg": p["cfg"]}
    legacy_default = clean_convert(PRESET_DEFAULTS[kind])
    if clean_convert(flat) == legacy_default and kind not in conf()["default_for"]:          # nie angefasst: neuer mitgelieferter Standard
        return {"id": p["id"], "cfg": p["cfg"]}
    same = {k: v for k, v in clean_convert(flat).items() if k not in ("convert", "origin")} == {k: v for k, v in p["cfg"].items() if k not in ("convert", "origin")}
    return {"id": p["id"] if same else "", "cfg": clean_convert(flat)}


def sync_flat(old: dict, new: dict):
    """Die gewählten Standard-Presets auch in die alten flachen Felder schreiben (alte Oberflächen, Rip-Voreinstellung)."""
    for kind in PRESET_DEFAULTS:
        pid = new.get("default_for", {}).get(kind)
        p = find_preset(pid) if pid else None
        if p:
            settings.setdefault("presets", {})[kind] = {**p["cfg"], "convert": False}


ext.register_settings("convert", ConvertSettings, {"presets": {}, "default_for": {}}, on_change=sync_flat)


def save_conf():
    from app.settings import save_settings
    save_settings()
    broadcast()


# ---------------------------------------------------------------- Rechner (dieser und andere) für Vorhersage und „Ausführen auf“
def node_list(cfg: dict) -> list[dict]:
    me = {"name": INSTANCE, "local": True, "cores": os.cpu_count() or 1, "load": 0.0, "speed": convert_stats.speed_table(), "ok": True, "reason": ""}
    try:
        me["load"] = round(os.getloadavg()[0], 2)
    except OSError:
        pass
    why = convert_caps.unusable(cfg, convert_caps_sample())
    me.update(ok=not why, reason=why)
    out = [me]
    for p in sorted(peers_state.values(), key=lambda x: x["name"]):
        ok, reason = convert_caps.peer_ok(cfg, p)
        c = (p.get("capabilities") or {}).get("convert") or {}
        out.append({"name": p["name"], "local": False, "cores": p.get("cores") or c.get("cores") or 0, "load": p.get("load", 0), "speed": c.get("speed") or {},
                    "ok": ok, "reason": reason, "legacy": bool(p.get("legacy") or not p.get("capabilities"))})
    return out


def convert_caps_sample() -> dict:
    from app.ffmpeg_args import SAMPLE_INFO
    return SAMPLE_INFO


def src_from_lib(path: str) -> dict | None:
    from app import library
    c = library.lib_cache.get(path)
    if not c or not c.get("info"):
        return None
    i = c["info"]
    return {"path": path, "size": c["size"], "dur": i["dur"], "w": i["w"], "h": i["h"], "fps": i.get("fps") or 24.0, "audio": i["audio"], "abytes": i.get("abytes", 0),
            "hdr": i["hdr"], "codec": i["codec"]}


def predict(cfg: dict, srcs: list[dict]) -> dict:
    size = n_size = 0
    for s in srcs:
        b, n = convert_stats.estimate_size(cfg, s)
        size += b
        n_size = max(n_size, n)
    nodes = []
    for nd in node_list(cfg):
        secs, n = 0.0, 0
        for s in srcs:
            t, k = convert_stats.estimate_secs(cfg, s, nd["cores"], nd["name"], nd["speed"])
            secs, n = secs + t, max(n, k)
        nodes.append({"name": nd["name"], "local": nd["local"], "ok": nd["ok"], "reason": nd["reason"], "secs": round(secs), "samples": n, "cores": nd["cores"],
                      "load": nd["load"], "legacy": nd.get("legacy", False)})
    return {"in_bytes": sum(s["size"] for s in srcs), "out_bytes": size, "samples": n_size, "nodes": nodes}


class CfgReq(BaseModel):
    cfg: dict = {}
    files: list[dict] = []          # Beispieldateien: {path} aus der Bibliothek oder {size, dur, w, h, fps, audio}
    paths: list[str] = []


def srcs_of(req: CfgReq) -> list[dict]:
    out = [s for s in (src_from_lib(p) for p in req.paths[:500]) if s]
    for f in req.files[:50]:
        if f.get("path") and (s := src_from_lib(str(f["path"]))):
            out.append(s)
        elif f.get("size") and f.get("dur"):
            out.append({"size": int(f["size"]), "dur": float(f["dur"]), "w": int(f.get("w") or 1920), "h": int(f.get("h") or 1080), "fps": float(f.get("fps") or 24),
                        "audio": f.get("audio") or ["ac3 6ch"], "abytes": int(f.get("abytes") or 0)})
    return out


@router.get("/meta")
def api_meta():
    codecs = {k: {**{a: b for a, b in c.items() if a not in ("rel",)}, "id": k, "available": k in convert_caps.codecs_available()} for k, c in CODECS.items()}
    return {"schema": SCHEMA, "codecs": codecs, "presets": all_presets(), "defaults": {k: default_for(k) for k in DEFAULT_FOR}, "caps": convert_caps.public_caps(convert_stats.speed_table())["convert"],
            "stats": convert_stats.summary(), "instance": INSTANCE, "scale": {c: {"worst": CODECS[c]["q"][0], "best": CODECS[c]["q"][1]} for c in CODECS},
            "words": [[80, "optisch verlustfrei"], [56, "hoch"], [33, "ausgewogen"], [12, "klein"], [0, "sehr klein"]]}


@router.post("/normalize")
def api_normalize(req: CfgReq):
    cfg = clean_convert(req.cfg)
    return {"cfg": cfg, "v1_compatible": is_v1_compatible(cfg), "summary": describe(cfg), "command": command_preview(cfg)}


@router.post("/translate")
def api_translate(req: CfgReq):
    """Codec wechseln und die Qualität auf die gleiche Wahrnehmungsstufe legen: {cfg, to: codec}."""
    cfg = clean_convert(req.cfg)
    to = req.files[0].get("to") if req.files else ""
    if to not in CODECS:
        raise HTTPException(400, "Unbekannter Codec")
    lvl = crf_to_level(cfg["video"]["codec"], cfg["quality"]["crf"])
    new = {**cfg, "video": {**cfg["video"], "codec": to, "speed": CODECS[to]["speed_def"], "extra": "", "hw": "hevc_vaapi" if to == "hw" else ""},
           "quality": {**cfg["quality"], "crf": level_to_crf(to, lvl)}}
    return {"cfg": clean_convert(new)}


@router.post("/estimate")
def api_estimate(req: CfgReq):
    cfg = clean_convert(req.cfg)
    srcs = srcs_of(req) or [{"size": 24 * 1024 ** 3, "dur": 7200.0, "w": 1920, "h": 1080, "fps": 23.976, "audio": ["dts 6ch", "ac3 6ch"]}]
    return {**predict(cfg, srcs), "example": not (req.paths or req.files), "files": len(srcs)}


@router.get("/stats")
def api_stats():
    return {**convert_stats.summary(), "records": convert_stats.records[-50:]}


# ---------------------------------------------------------------- eigene Presets
class PresetReq(BaseModel):
    name: str
    desc: str = ""
    cfg: dict = {}


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")).strip("-")[:20] or "preset"
    pid, i = s, 2
    while find_preset(pid):
        pid, i = f"{s}-{i}", i + 1
    return pid


@router.post("/presets")
def api_preset_create(req: PresetReq):
    if not req.name.strip():
        raise HTTPException(400, "Der Name fehlt.")
    pid = _slug(req.name)
    conf()["presets"][pid] = {"name": req.name.strip()[:60], "desc": req.desc.strip()[:200], "cfg": {**clean_convert({**req.cfg, "convert": True}), "origin": pid}}
    save_conf()
    return find_preset(pid)


@router.patch("/presets/{pid}")
def api_preset_update(pid: str, req: PresetReq):
    if pid not in conf()["presets"]:
        raise HTTPException(404, "Eigenes Preset nicht gefunden (mitgelieferte lassen sich nicht ändern; zuerst kopieren).")
    p = conf()["presets"][pid]
    p["name"] = req.name.strip()[:60] or p["name"]
    p["desc"] = req.desc.strip()[:200]
    if req.cfg:
        p["cfg"] = {**clean_convert({**req.cfg, "convert": True}), "origin": pid}
    save_conf()
    return find_preset(pid)


@router.delete("/presets/{pid}")
def api_preset_delete(pid: str):
    if pid in BUILTIN_IDS:
        raise HTTPException(409, "Mitgelieferte Presets lassen sich nicht löschen.")
    if conf()["presets"].pop(pid, None) is None:
        raise HTTPException(404, "Preset nicht gefunden")
    conf()["default_for"] = {k: v for k, v in conf()["default_for"].items() if v != pid}
    save_conf()
    return {"ok": True}


class DefaultReq(BaseModel):
    kind: str
    preset: str


@router.post("/defaults")
def api_default(req: DefaultReq):
    if req.kind not in DEFAULT_FOR or not find_preset(req.preset):
        raise HTTPException(400, "Unbekannte Disc-Art oder unbekanntes Preset")
    conf()["default_for"][req.kind] = req.preset
    sync_flat({}, conf())
    save_conf()
    return {k: default_for(k) for k in DEFAULT_FOR}


# ---------------------------------------------------------------- Start auf diesem oder einem anderen Rechner
class StartReq(BaseModel):
    target: str = "local"
    paths: list[str] = []
    convert: dict = {}
    takeover_from: str = ""


def _peer_post(name: str, path: str, body: dict, timeout: float = 30.0):
    fn = getattr(cluster, "peer_call", None)
    if fn:
        return fn(name, path, body, timeout=timeout)
    return cluster._http_json(f"{peers_state[name]['url']}/api/{path}", body, timeout)


@router.post("/start")
async def api_start(req: StartReq):
    """Bibliotheks-Dateien konvertieren lassen, auf diesem Rechner oder einem anderen. Ein Rechner, der die Einstellungen nicht versteht
    (alter Stand) oder dem ein Encoder fehlt, bekommt den Auftrag nie – sonst würde er still mit x265-Standard kodieren."""
    from app import library
    cfg = clean_convert({**req.convert, "convert": True})
    if req.target in ("", "local", INSTANCE):
        return await library.api_library_convert(library.LibReq(paths=req.paths, convert=cfg, takeover_from=req.takeover_from))
    peer = peers_state.get(req.target)
    if not peer:
        raise HTTPException(404, f"Rechner „{req.target}“ ist nicht bekannt.")
    ok, why = convert_caps.peer_ok(cfg, peer)
    if not ok:
        raise HTTPException(409, f"{req.target}: {why}")
    legacy = peer.get("legacy") or not (peer.get("capabilities") or {})
    body = {"paths": req.paths, "convert": to_v1(cfg) if legacy else cfg, "takeover_from": req.takeover_from}
    try:
        return await asyncio.to_thread(_peer_post, req.target, "library/convert", body, 30.0)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"{req.target} antwortet nicht: {e}")


async def startup():
    from app import convert_stats as st
    st.load()
    await convert_caps.probe_capabilities()


router.include_router(convert_probe.router)
ext.register_router(router)
convert_caps.publish()
ext.register_startup(startup)
