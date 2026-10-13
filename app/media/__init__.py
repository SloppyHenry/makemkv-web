"""Package PE: Jellyfin filing – detection, metadata (TMDB), naming after the Jellyfin scheme, sorting with preview and undo.

Registers on import via app.ext (loaded automatically by main.py):
router /api/media, settings `media` (secret fields tmdb_key and jellyfin_key), rip hook for the companion file (DATA/media/discs.json),
upload hook (record the actual target path), capability `media`, state field `media`.
"""
from pathlib import Path

from app import ext
from app.media import api, auto, conf, organize, store

ext.register_router(api.router)
ext.register_settings("media", conf.MediaSettings, conf.DEFAULTS, secret=("tmdb_key", "jellyfin_key"))
ext.register_rip_hook(store.remember_rip)
ext.register_capability("media", {"v": 1, "naming": ["jellyfin", "unveraendert"]})


def _on_upload(item: dict):
    """The transfer may have chosen a different name (`unique_path`): store the companion data under the actual path."""
    dest = item.get("dest")
    if dest and item.get("name"):
        store.rekey_file(item["name"], organize.key_for(Path(dest)))
    auto.schedule(str(Path(item.get("name") or "").parent) if "/" in (item.get("name") or "") else "")


ext.register_upload_hook(_on_upload)


def _snapshot() -> dict:
    last = organize.last_undoable()
    st = conf.cfg()
    return {"running": any(o["status"] == "running" for o in organize.ops.values()), "undo": last["id"] if last else None,
            "configured": bool(st["movies_dir"] or st["series_dir"]), "tmdb": bool(st["tmdb_key"])}


ext.register_snapshot("media", _snapshot)
