"""Einstellungen (Namensraum `media`), Wurzelordner für die Ordnerauswahl und Prüfung der Ablageordner."""
import os
import re
import shutil
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, field_validator

from app import files, state
from app.config import OUT_MOUNT

# Vorbelegung: Ordner direkt im eingehängten Ziel (so heißt es im Container wirklich); angelegt wird nichts, geprüft nur auf Wunsch (check-dir)
DEFAULTS = {"movies_dir": f"{OUT_MOUNT.rstrip('/')}/Filme", "series_dir": f"{OUT_MOUNT.rstrip('/')}/Serien",
            "naming": "jellyfin", "action": "verschieben", "tmdb_key": "", "language": "de-DE",
            "id_tags": True, "episode_names": False, "jellyfin_url": "", "jellyfin_key": "", "jellyfin_scan": False, "auto": False}


class MediaSettings(BaseModel):
    movies_dir: str = DEFAULTS["movies_dir"]
    series_dir: str = DEFAULTS["series_dir"]
    naming: Literal["jellyfin", "unveraendert"] = "jellyfin"
    action: Literal["verschieben", "kopieren"] = "verschieben"
    tmdb_key: str = ""
    language: str = "de-DE"
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
            raise ValueError("Pfad muss absolut sein und darf kein „..“ enthalten")
        return v.rstrip("/") if len(v) > 1 else v

    @field_validator("language")
    @classmethod
    def _lang(cls, v: str):
        v = v.strip()
        if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", v):
            raise ValueError("Sprache im Format de-DE")
        return v

    @field_validator("jellyfin_url")
    @classmethod
    def _url(cls, v: str):
        v = v.strip().rstrip("/")
        if v and not re.match(r"https?://[^\s/]+", v):
            raise ValueError("Adresse muss mit http:// oder https:// beginnen")
        return v


def cfg() -> dict:
    """Aktuelle Einstellungen (mit Vorgaben aufgefüllt)."""
    return {**DEFAULTS, **(state.settings.get("media") or {})}


def media_root() -> Path:
    """Obergrenze für Ordnerauswahl und Ablage: das eingehängte NAS (`OUTPUT_MOUNT`), sonst der Ausgabeordner. `MEDIA_ROOT` überschreibt (Entwicklung)."""
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
        raise HTTPException(400, "Der Ordner muss innerhalb des eingehängten Ziels liegen.")
    return p


def check_dir(path: str) -> dict:
    """Ablageordner prüfen: liegt im Ziel, ist ein Ordner, ist beschreibbar. {ok, exists, writable, free, why}."""
    if not path:
        return {"ok": False, "exists": False, "writable": False, "free": 0, "why": "nicht festgelegt"}
    try:
        p = inside_root(path)
    except HTTPException as e:
        return {"ok": False, "exists": False, "writable": False, "free": 0, "why": e.detail}
    if not p.exists():
        parent = next((a for a in p.parents if a.exists()), None)
        ok = bool(parent and os.access(parent, os.W_OK))
        return {"ok": ok, "exists": False, "writable": ok, "free": 0, "why": "Ordner existiert noch nicht, wird beim ersten Einsortieren angelegt" if ok else "nicht beschreibbar"}
    if not p.is_dir():
        return {"ok": False, "exists": True, "writable": False, "free": 0, "why": "ist kein Ordner"}
    w = os.access(p, os.W_OK)
    return {"ok": w, "exists": True, "writable": w, "free": shutil.disk_usage(p).free, "why": "" if w else "nicht beschreibbar (Rechte auf dem NAS prüfen)"}
