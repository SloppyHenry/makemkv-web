"""HTTP-Schnittstelle `/api/media/…` (Einstellungen prüfen, Suche, Erkennen, Einsortieren, Verlauf, Info)."""
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.media import analyze, conf, info, jellyfin, metadata, organize, plan as planner
from app.util import mkdir_open, valid_name

router = APIRouter(prefix="/api/media")


def _meta_error(e: metadata.MetadataError):
    raise HTTPException(401 if e.code == "bad_key" else 404 if e.code == "not_found" else 502, str(e))


# ---- Einstellungen: Ordner und Verbindungen prüfen
@router.get("/check-dir")
def check_dir(path: str = ""):
    return conf.check_dir(path)


@router.get("/browse")
def browse(path: str = ""):
    """Unterordner innerhalb des eingehängten Ziels (für die Ordnerauswahl)."""
    root = conf.media_root()
    p = conf.inside_root(path)
    if not p.is_dir():
        raise HTTPException(404, "Ordner nicht gefunden")
    dirs = []
    try:
        for e in sorted(os.scandir(p), key=lambda x: x.name.lower()):
            if e.is_dir(follow_symlinks=False) and not e.name.startswith(".") and len(dirs) < 500:
                dirs.append({"name": e.name, "path": e.path})
    except OSError as e:
        raise HTTPException(403, f"Ordner nicht lesbar: {e}")
    return {"root": str(root), "path": str(p), "parent": str(p.parent) if p != root else "", "dirs": dirs, "writable": os.access(p, os.W_OK)}


class MkdirReq(BaseModel):
    path: str
    name: str


@router.post("/mkdir")
def mkdir(req: MkdirReq):
    p = conf.inside_root(req.path) / valid_name(req.name)
    if p.exists():
        raise HTTPException(409, "Ordner existiert schon")
    try:
        mkdir_open(p, conf.media_root())
    except OSError as e:
        raise HTTPException(403, f"Ordner konnte nicht angelegt werden: {e}")
    return {"path": str(p)}


class KeyReq(BaseModel):
    key: str | None = None            # None = den gespeicherten Schlüssel prüfen
    url: str | None = None


@router.post("/tmdb/test")
async def tmdb_test(req: KeyReq):
    return await metadata.test_key(req.key if req.key else conf.cfg()["tmdb_key"])


@router.post("/jellyfin/test")
async def jellyfin_test(req: KeyReq):
    st = conf.cfg()
    return await jellyfin.test(req.url or st["jellyfin_url"], req.key or st["jellyfin_key"])


@router.post("/cache/clear")
def cache_clear():
    metadata.clear_cache()
    return {"ok": True}


@router.get("/cache")
def cache_info():
    return {"entries": metadata.cache_size()}


# ---- Metadaten
@router.get("/search")
async def search(q: str, type: str = "tv", year: int | None = None):
    """Titelvorschläge (type: movie | tv). Ohne Schlüssel `{available: false}` – die Oberfläche fragt dann von Hand."""
    st = conf.cfg()
    if not st["tmdb_key"]:
        return {"available": False, "results": []}
    if type not in ("movie", "tv"):
        raise HTTPException(400, "type muss movie oder tv sein")
    try:
        return {"available": True, "results": await metadata.search(st["tmdb_key"], type, q, year, st["language"])}
    except metadata.MetadataError as e:
        _meta_error(e)


@router.get("/find")
async def find(imdb: str):
    st = conf.cfg()
    if not st["tmdb_key"]:
        return {"available": False, "result": None}
    try:
        hit = await metadata.find_imdb(st["tmdb_key"], imdb, st["language"])
        return {"available": True, "result": hit and {**hit, **await metadata.details(st["tmdb_key"], hit["kind"], hit["tmdb"], st["language"])}}
    except metadata.MetadataError as e:
        _meta_error(e)


@router.get("/title")
async def title(type: str, id: int):
    st = conf.cfg()
    try:
        return await metadata.details(st["tmdb_key"], type, id, st["language"])
    except metadata.MetadataError as e:
        _meta_error(e)


class DetectReq(BaseModel):
    paths: list[str]


@router.post("/detect")
async def detect_(req: DetectReq):
    if not req.paths:
        raise HTTPException(400, "Keine Dateien gewählt")
    return await analyze.analyze(req.paths)


class AssignReq(BaseModel):
    items: list[dict]                 # [{path, role, dur}]
    season: int = 1
    start: int = 1
    tmdb: int | None = None


@router.post("/episodes")
async def episodes(req: AssignReq):
    """Episoden neu zuordnen (anderer Titel, andere Staffel oder Startfolge gewählt)."""
    st = conf.cfg()
    return await analyze.episodes_for(req.items, req.season, req.start, req.tmdb, st["tmdb_key"], st["language"])


# ---- Einsortieren
class PlanReq(BaseModel):
    kind: str
    title: str = ""
    year: int | None = None
    tmdb: int | None = None
    imdb: str | None = None
    poster: str | None = None
    season: int | None = None
    disc: int | None = None
    items: list[dict]
    decisions: dict = {}


@router.post("/plan")
def plan_(req: PlanReq):
    try:
        return planner.build_plan(req.model_dump())
    except planner.PlanError as e:
        raise HTTPException(400, str(e))


@router.post("/run")
async def run(req: PlanReq):
    try:
        return await organize.start(req.model_dump())
    except planner.PlanError as e:
        raise HTTPException(409, str(e))


@router.get("/run/{oid}")
def run_status(oid: str):
    op = organize.ops.get(oid)
    if not op:
        raise HTTPException(404, "Aktion unbekannt")
    return op


@router.get("/history")
def history():
    last = organize.last_undoable()
    return {"items": [{**{k: h[k] for k in ("id", "t", "title", "kind", "action", "undone")}, "files": len(h["rows"]), "can_undo": bool(last and last["id"] == h["id"])}
                      for h in reversed(organize.history())]}


@router.post("/undo/{oid}")
def undo(oid: str):
    try:
        return organize.undo(oid)
    except planner.PlanError as e:
        raise HTTPException(409, str(e))


# ---- Info für die Bibliothek (PF)
@router.get("/info")
def info_one(path: str):
    return info.info_for(path)


class InfoReq(BaseModel):
    paths: list[str]


@router.post("/info")
def info_many(req: InfoReq):
    return {"items": [info.info_for(p) for p in req.paths[:2000]]}

