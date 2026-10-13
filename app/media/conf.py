"""Settings (namespace `media`), root folder for the folder selection and checks of the storage folders."""
import os
import re
import shutil
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, field_validator

from app import files, state
from app.config import OUT_MOUNT

# Defaults: folders directly in the mounted target (that is what it is really called in the container); nothing is created, checked only on request (check-dir)
DEFAULTS = {"movies_dir": f"{OUT_MOUNT.rstrip('/')}/Movies", "series_dir": f"{OUT_MOUNT.rstrip('/')}/Series",
            "naming": "jellyfin", "action": "verschieben", "tmdb_key": "", "language": "en-US",
            "id_tags": True, "episode_names": False, "jellyfin_url": "", "jellyfin_key": "", "jellyfin_scan": False, "auto": False}


class MediaSettings(BaseModel):
    movies_dir: str = DEFAULTS["movies_dir"]
    series_dir: str = DEFAULTS["series_dir"]
    naming: Literal["jellyfin", "unveraendert"] = "jellyfin"          # stored values: "unveraendert" = unchanged
    action: Literal["verschieben", "kopieren"] = "verschieben"         # stored values: "verschieben" = move, "kopieren" = copy
    tmdb_key: str = ""
    language: str = "en-US"
    id_tags: bool = True
    episode_names: bool = False
    jellyfin_url: str = ""
    jellyfin_key: str = ""
    jellyfin_scan: bool = False
    auto: bool = False

    @field_validator("movies_dir", "series_dir", "tmdb_key", "jellyfin_key", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("movies_dir", "series_dir")
    @classmethod
    def _abs(cls, v: str):
        if v and (not v.startswith("/") or ".." in v.split("/")):
            raise ValueError("The path must be absolute and must not contain \"..\"")
        return v.rstrip("/") if len(v) > 1 else v

    @field_validator("language")
    @classmethod
    def _lang(cls, v: str):
        v = v.strip()
        if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", v):
            raise ValueError("Language in the format en-US")
        return v

    @field_validator("jellyfin_url")
    @classmethod
    def _url(cls, v: str):
        v = v.strip().rstrip("/")
        if v and not re.match(r"https?://[^\s/]+", v):
            raise ValueError("The address must start with http:// or https://")
        return v


def cfg() -> dict:
    """Current settings (filled up with the defaults)."""
    return {**DEFAULTS, **(state.settings.get("media") or {})}


def media_root() -> Path:
    """Upper limit for folder selection and filing: the mounted NAS (`OUTPUT_MOUNT`), otherwise the output folder. `MEDIA_ROOT` overrides it (development)."""
    env = os.environ.get("MEDIA_ROOT")
    if env:
        return Path(env).resolve()
    if files.mount_ok():
        return Path(OUT_MOUNT).resolve()
    return files.out_dir()[0].resolve()


def inside_root(path: str) -> Path:
    root = media_root()
    p = Path(path or str(root)).resolve()
    if p != root and root not in p.parents:
        raise HTTPException(400, "The folder must be inside the mounted target.")
    return p


def check_dir(path: str) -> dict:
    """Check a storage folder: inside the target, is a folder, is writable. {ok, exists, writable, free, why}."""
    if not path:
        return {"ok": False, "exists": False, "writable": False, "free": 0, "why": "not set"}
    try:
        p = inside_root(path)
    except HTTPException as e:
        return {"ok": False, "exists": False, "writable": False, "free": 0, "why": e.detail}
    if not p.exists():
        parent = next((a for a in p.parents if a.exists()), None)
        ok = bool(parent and os.access(parent, os.W_OK))
        return {"ok": ok, "exists": False, "writable": ok, "free": 0, "why": "folder does not exist yet, it is created on the first sort" if ok else "not writable"}
    if not p.is_dir():
        return {"ok": False, "exists": True, "writable": False, "free": 0, "why": "is not a folder"}
    w = os.access(p, os.W_OK)
    return {"ok": w, "exists": True, "writable": w, "free": shutil.disk_usage(p).free, "why": "" if w else "not writable (check the permissions on the NAS)"}
