"""MakeMKV-Web: headless MakeMKV mit Browser-Oberfläche.

- erkennt Laufwerke (/dev/sr*) und eingelegte Discs live (ioctl, kein Eingriff in laufende Jobs)
- analysiert neu eingelegte Discs automatisch (makemkvcon info)
- rippt gewählte Titel als MKV oder macht ein entschlüsseltes Disc-Backup
- Ausgabe nach /mnt/nas/rips, solange eingehängt (sonst lokaler Fallback)

Diese Datei erzeugt nur die App, bindet die Router ein und startet die Hintergrundaufgaben.
Erweiterungspunkte: app/ext.py, Beschreibung in docs/agenten/schnittstellen.md
"""
import asyncio
import importlib

from fastapi import FastAPI

from app import (auth, cluster, convert, drives, ext, files, joblist, library, makemkv, rip, settings, state,
                 ui, upload)
from app.config import DATA, FEATURES, VERSION

# Optionale Module der Arbeitspakete. Sie melden sich beim Import selbst über app.ext an (Router, Einstellungen, Hooks …).
# Fehlt ein Modul, wird es übersprungen; ein Fehler darin bricht den Start ab (damit er nicht untergeht).
OPTIONAL_MODULES = ["app.nodes", "app.player", "app.media", "app.convert_presets"]

app = FastAPI(title="MakeMKV-Web")
app.middleware("http")(auth.basic_auth)

ext.register_capability("version", VERSION)
ext.register_capability("features", FEATURES)
ext.register_capability("jobs_dismiss", True)    # beendete Aufträge lassen sich aus der Liste entfernen

for _name in OPTIONAL_MODULES:
    try:
        importlib.import_module(_name)
    except ModuleNotFoundError as e:
        if e.name != _name:
            raise

for _router in (state.router, drives.router, rip.router, convert.router, library.router, files.router,
                settings.router, makemkv.router, cluster.router, joblist.router, *ext.routers):
    app.include_router(_router)
app.mount("/static", ui.NoCacheStatic(directory=ui.STATIC), name="static")
app.include_router(ui.router)


@app.on_event("startup")
async def startup():
    DATA.mkdir(parents=True, exist_ok=True)
    settings.load_settings()
    asyncio.create_task(drives.poller())
    asyncio.create_task(makemkv.key_refresher())
    asyncio.create_task(files.output_refresher())
    upload.recover_staging()
    library.load_cache()
    asyncio.create_task(library.lib_probe_worker())
    asyncio.create_task(files.lock_heartbeat())
    asyncio.create_task(cluster.peer_prober())   # fragt die Rechnerliste ab (auch wenn sie erst später gefüllt wird)
    asyncio.create_task(upload.upload_worker())
    asyncio.create_task(convert.convert_worker())
    ext.start_all()
