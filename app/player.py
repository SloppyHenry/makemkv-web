"""Interner Player: Probe, Wiedergabe-Entscheidung, Strom (Direkt/Remux/Transkodieren), Untertitel. Router unter /api/player.

Ablauf: `POST /session` (oder `GET /probe` zum Anzeigen) -> die Oberfläche bekommt entweder die Adresse der Originaldatei (`/file`, HTTP-Range, direkt)
oder die eines ffmpeg-Stroms (`/stream/{id}`, fragmentiertes MP4). Suchen = neue Sitzung mit anderem `start`.
Konzept und Begründung: docs/agenten/status-paket-d.md
"""
import asyncio
import json
from urllib.parse import quote
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field, field_validator

from app import ext
from app import player_stream as ps
from app.player_probe import MIME, check_path, parse_caps, pick_audio, plan as make_plan, preferred_tracks, probe_file
from app.state import settings

router = APIRouter(prefix="/api/player")


class PlayerSettings(BaseModel):
    transcode: bool = True                                       # Umwandeln (Transkodieren) überhaupt erlauben (nur wenn der Browser das Video nicht kann)
    max_height: int = Field(0, ge=0, le=2160)                    # höchste Auflösung beim Umwandeln; 0 = Original (nicht verkleinern)
    crf: int = Field(24, ge=16, le=35)                           # x264-Qualität beim Umwandeln (kleiner = besser)
    preset: Literal["ultrafast", "superfast", "veryfast", "faster", "fast"] = "veryfast"
    audio_lang: str = Field("", max_length=60)                   # bevorzugte Tonsprache, z. B. "deu,eng"; leer = Vorgabe der Datei (dann "audio_langs" aus Allgemein)
    sub_lang: str = Field("", max_length=60)                     # bevorzugte Untertitelsprache; leer = nur die in der Datei als Standard/erzwungen markierte Spur

    @field_validator("max_height")
    @classmethod
    def _height(cls, v):
        if v and v < 240:
            raise ValueError("0 (Original) oder mindestens 240")
        return v


DEFAULTS = PlayerSettings().model_dump()
ext.register_router(router)
ext.register_settings("player", PlayerSettings, DEFAULTS)
ext.register_capability("player", {"v": 1, "modes": ["direct", "remux"], "encoders": [], "tonemap": False, "max_transcodes": ps.MAX_TRANSCODES, "subtitles": ["text"]})


def cfg() -> dict:
    return {**DEFAULTS, **(settings.get("player") or {})}


def pref_langs() -> tuple[str, str]:
    """Bevorzugte Sprachen: eigene Einstellung, beim Ton sonst die allgemeine Rip-Sprachliste als Voreinschlag."""
    c = cfg()
    return c["audio_lang"] or settings.get("audio_langs", ""), c["sub_lang"]


def _public_info(rel: str, p, info: dict, pl: dict, locked) -> dict:
    pref = preferred_tracks(info, *pref_langs())
    return {"path": rel, "name": p.name, "size": info["size"], "duration": info["duration"], "container": info["container"], "video": info["video"],
            "audio": info["audio"], "subs": [{**x, "supported": x["kind"] == "text"} for x in info["subs"]],      # Bildspuren: nicht unterstützt
            "preferred": {"audio": pref[0], "sub": pref[1]}, "chapters": info["chapters"], "plan": pl, "locked": locked, "busy": ps.busy_info(),
            "transcode_allowed": cfg()["transcode"], "limits": {"transcode_busy": any(s["plan"]["video"] == "x264" and ps.alive(s) for s in ps.sessions.values())}}


async def _probe(path: str, caps, audio, force):
    p = check_path(path)
    info = await probe_file(p)
    pref = preferred_tracks(info, *pref_langs())[0]
    pl = make_plan(info, parse_caps(caps), audio, force, cfg()["transcode"], p.suffix.lower(), pref)
    return p, info, pl


@router.get("/probe")
async def api_probe(path: str, caps: str = "", audio: int | None = None, force: str = "auto"):
    p, info, pl = await _probe(path, caps, audio, force)
    return _public_info(path, p, info, pl, ps.lock_info(path, p))


class ProbeReq(BaseModel):
    path: str
    caps: str = ""
    audio: int | None = None
    force: Literal["auto", "remux"] = "auto"


@router.post("/probe")
async def api_probe_post(req: ProbeReq):            # für den Verbund-Proxy (POST)
    return await api_probe(req.path, req.caps, req.audio, req.force)


class SessionReq(ProbeReq):
    client: str = Field("", max_length=64)           # zufällige Kennung des Browser-Tabs (ein Strom je Tab)
    start: float = Field(0, ge=0)


@router.post("/session")
async def api_session(req: SessionReq):
    """Wiedergabe starten oder an anderer Stelle neu starten. Antwort: url, mode, start (tatsächlicher Beginn in s), duration, plan."""
    p, info, pl = await _probe(req.path, req.caps, req.audio, req.force)
    if not pl["ok"]:
        raise HTTPException(422, pl["error"])
    base = {"mode": pl["mode"], "plan": pl, "duration": info["duration"], "locked": ps.lock_info(req.path, p), "busy": ps.busy_info()}
    if pl["mode"] == "direct":
        ps.drop_client(req.client)
        return {**base, "id": "", "url": "/api/player/file?path=" + _q(req.path), "start": 0.0, "native_seek": True}
    start = min(req.start, max(info["duration"] - 1, 0)) if info["duration"] else req.start
    if pl["video"] == "copy":
        start = await ps.keyframe_before(p, start)         # bei Video-Kopie genau auf einen Keyframe starten (Bild und Ton bleiben gleich)
    tonemap = bool(ext.capabilities["player"].get("tonemap"))
    eff = pick_audio(info, req.audio, preferred_tracks(info, *pref_langs())[0])
    s = ps.new_session(req.client, req.path, p, start, info, pl, eff["i"] if eff else None, cfg(), tonemap)
    return {**base, "id": s["id"], "url": f"/api/player/stream/{s['id']}", "start": start, "native_seek": False, "threads": s["threads"], "nice": s["nice"]}


def _q(path: str) -> str:
    return quote(path, safe="")


@router.get("/stream/{sid}")
async def api_stream(sid: str):
    s = ps.sessions.get(sid)
    if not s:
        raise HTTPException(404, "Diese Wiedergabe ist abgelaufen. Bitte neu starten.")
    first = await ps.start_process(s)
    return ps.StreamResponse(s, first)


@router.get("/file")
def api_file(path: str):
    """Originaldatei mit HTTP-Range (nur für den Weg „direkt“). Gesperrte Dateien bleiben lesbar."""
    p = check_path(path)
    return FileResponse(p, media_type=MIME.get(p.suffix.lower(), "application/octet-stream"), headers={"Cache-Control": "no-store"})


@router.get("/subtitle")
async def api_subtitle(path: str, index: int):
    p = check_path(path)
    info = await probe_file(p)
    return PlainTextResponse(await ps.subtitle_vtt(p, info, index), media_type="text/vtt; charset=utf-8", headers={"Cache-Control": "private, max-age=3600"})


@router.post("/stop")
async def api_stop(request: Request):
    """Wiedergabe dieses Browsers beenden. Auch per navigator.sendBeacon beim Schließen (Text-Body {"client": "…"})."""
    try:
        client = str(json.loads((await request.body()) or b"{}").get("client", ""))
    except (ValueError, AttributeError):
        client = ""
    ps.drop_client(client)
    return {"ok": True}


@router.get("/sessions")
def api_sessions():
    return ps.public_sessions()


# ---------------------------------------------------------------- Fähigkeiten und Wächter

async def _detect():
    """Einmal beim Start: Was kann das ffmpeg dieses Rechners? (landet in den Fähigkeiten, sichtbar im Verbund)"""
    async def out(*a):
        pr = await asyncio.create_subprocess_exec("ffmpeg", "-hide_banner", *a, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        return (await pr.communicate())[0].decode(errors="replace")
    try:
        enc, flt = await out("-encoders"), await out("-filters")
    except OSError:
        return
    modes = ["direct", "remux"] + (["transcode"] if " libx264 " in enc else [])
    ext.capabilities["player"].update({"modes": modes, "encoders": [e for e in ("libx264",) if f" {e} " in enc], "tonemap": " zscale " in flt and " tonemap " in flt})


async def _startup():
    ps.prune_cache()
    asyncio.create_task(_detect())
    await ps.janitor()


ext.register_startup(_startup)
