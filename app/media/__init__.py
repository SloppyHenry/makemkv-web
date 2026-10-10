"""Paket PE: Jellyfin-Ablage – Erkennen, Metadaten (TMDB), Benennen nach Jellyfin-Schema, Einsortieren mit Vorschau und Rückgängig.

Meldet sich beim Import über app.ext an (wird von main.py automatisch geladen):
Router /api/media, Einstellungen `media` (Geheimnisfelder tmdb_key und jellyfin_key), Rip-Hook für die Begleitdatei (DATA/media/discs.json),
Upload-Hook (echten Zielpfad nachtragen), Fähigkeit `media`, Statusfeld `media`.
"""
from pathlib import Path

from app import ext
from app.media import api, conf, organize, store

ext.register_router(api.router)
ext.register_settings("media", conf.MediaSettings, conf.DEFAULTS, secret=("tmdb_key", "jellyfin_key"))
ext.register_rip_hook(store.remember_rip)
ext.register_capability("media", {"v": 1, "naming": ["jellyfin", "unveraendert"], "tmdb": True})


def _on_upload(item: dict):
    """Die Übertragung kann einen anderen Namen gewählt haben (`unique_path`): Begleitdaten unter dem echten Pfad ablegen."""
    dest = item.get("dest")
    if dest and item.get("name"):
        store.rekey_file(item["name"], organize.key_for(Path(dest)))


ext.register_upload_hook(_on_upload)


def _snapshot() -> dict:
    last = organize.last_undoable()
    st = conf.cfg()
    return {"running": any(o["status"] == "running" for o in organize.ops.values()), "undo": last["id"] if last else None,
            "configured": bool(st["movies_dir"] or st["series_dir"]), "tmdb": bool(st["tmdb_key"])}


ext.register_snapshot("media", _snapshot)
