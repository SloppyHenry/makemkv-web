"""Einstellungen laden, speichern und über die API ändern.

Allgemeine Felder liegen flach in `settings` (Namensraum „general“). Erweiterungen melden einen eigenen Namensraum an
(`ext.register_settings`) und liegen dann als verschachteltes Objekt darin: `settings["media"]["movies_dir"]`.
"""
import asyncio
import inspect
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from app import ext
from app.config import BETAKEY, CONFIG, DATA, DEFAULTS, PRESET_DEFAULTS
from app.convert import clean_convert, ensure_conv_workers
from app.state import beta, broadcast, public_settings, settings

router = APIRouter()
_unknown: dict = {}      # Namensräume aus der Datei, deren Modul gerade nicht geladen ist (bleiben beim Speichern erhalten)


def _ns_values(ns: str, saved) -> dict:
    spec = ext.settings_ns[ns]
    try:
        return spec["model"](**{**spec["defaults"], **(saved if isinstance(saved, dict) else {})}).model_dump()
    except ValidationError:
        return dict(spec["defaults"])


def load_settings():
    saved = {}
    try:
        saved = json.loads(CONFIG.read_text())
        settings.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    settings["conv_parallel"] = max(1, min(int(settings.get("conv_parallel") or 1), 8))
    settings["conv_segments"] = max(0, min(int(settings.get("conv_segments") or 0), 12))
    presets = settings.get("presets") if isinstance(settings.get("presets"), dict) else {}
    settings["presets"] = {k: clean_convert({**PRESET_DEFAULTS[k], **(presets.get(k) or {})}) for k in PRESET_DEFAULTS}
    for ns in ext.settings_ns:
        settings[ns] = _ns_values(ns, saved.get(ns))
    _unknown.clear()
    _unknown.update({k: v for k, v in saved.items() if k not in DEFAULTS and k not in ext.settings_ns} if isinstance(saved, dict) else {})
    try:
        beta.update(json.loads(BETAKEY.read_text()))
    except (OSError, ValueError):
        pass


def save_settings():
    DATA.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps({**_unknown, **settings}, indent=2))


class SettingsReq(BaseModel):
    """Namensraum „general“ (die heutigen flachen Felder)."""
    minlength: int | None = None
    auto_scan: bool | None = None
    auto_eject: bool | None = None
    audio_langs: str | None = None
    sub_langs: str | None = None
    key: str | None = None
    presets: dict | None = None
    conv_parallel: int | None = None
    conv_segments: int | None = None


def apply_general(values: dict):
    try:
        req = SettingsReq(**{k: v for k, v in values.items() if k in SettingsReq.model_fields})
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_url=False, include_context=False, include_input=False))
    for k, v in req.model_dump(exclude_none=True).items():
        if k == "presets":
            for kind in PRESET_DEFAULTS:
                if isinstance(v.get(kind), dict):
                    settings["presets"][kind] = clean_convert({**settings["presets"][kind], **v[kind]})
            continue
        if k == "conv_parallel":
            v = max(1, min(int(v), 8))
        if k == "conv_segments":
            v = max(0, min(int(v), 12))
        if k == "minlength":
            v = max(0, min(int(v), 36000))
        settings[k] = v.strip() if isinstance(v, str) else v


def apply_namespace(ns: str, incoming: dict):
    spec = ext.settings_ns[ns]
    old = dict(settings.get(ns) or spec["defaults"])
    merged = {**old, **{k: v for k, v in incoming.items() if not (k in spec["secret"] and v is None)}}
    try:
        new = spec["model"](**merged).model_dump()
    except ValidationError as e:
        raise HTTPException(422, {ns: e.errors(include_url=False, include_context=False, include_input=False)})
    settings[ns] = new
    if spec["on_change"]:
        r = spec["on_change"](old, new)
        if inspect.isawaitable(r):
            asyncio.create_task(r)


@router.get("/api/settings")
async def api_settings_get():
    return public_settings()


@router.post("/api/settings")
async def api_settings(body: dict):
    """Flache Felder (wie bisher) und/oder Namensräume: {"general": {...}, "media": {...}}."""
    apply_general({**body, **(body.get("general") if isinstance(body.get("general"), dict) else {})})
    for ns in ext.settings_ns:
        if isinstance(body.get(ns), dict):
            apply_namespace(ns, body[ns])
    save_settings()
    ensure_conv_workers()
    broadcast()
    return public_settings()
