"""Spindle: headless MakeMKV with a browser interface.

- detects drives (/dev/sr*) and inserted discs live (ioctl, no interference with running jobs)
- analyzes newly inserted discs automatically (makemkvcon info)
- rips selected titles as MKV or makes a decrypted disc backup
- output to /mnt/nas/rips while it is mounted (otherwise a local fallback)

This file only creates the app, includes the routers and starts the background tasks.
Extension points: app/ext.py, description in docs/agents/schnittstellen.md
"""
import asyncio
import importlib

from fastapi import FastAPI

from app import (auth, cluster, convert, drives, ext, files, joblist, library, makemkv, rip, settings, state,
                 ui, upload)
from app.config import DATA, FEATURES, VERSION

# Optional modules of the work packages. They register themselves on import via app.ext (routers, settings, hooks …).
# A missing module is skipped; an error inside one aborts the start (so that it does not go unnoticed).
OPTIONAL_MODULES = ["app.nodes", "app.player", "app.media", "app.convert_presets", "app.headless"]

app = FastAPI(title="Spindle")
app.middleware("http")(auth.basic_auth)

ext.register_capability("version", VERSION)
ext.register_capability("features", FEATURES)
ext.register_capability("jobs_dismiss", True)    # finished jobs can be removed from the list

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
    asyncio.create_task(cluster.peer_prober())   # polls the machine list (even if it only gets filled later)
    asyncio.create_task(upload.upload_worker())
    asyncio.create_task(convert.convert_worker())
    ext.start_all()
