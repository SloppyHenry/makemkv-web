"""Rechnerverwaltung (Paket C): Betriebsart, eigene Identität, Rechnerliste, Verbindungstest.

Dieses Modul wird von main.py automatisch geladen (OPTIONAL_MODULES) und meldet sich über app.ext an. Die Teile:
  nodes_store.py  Rechnerliste (DATA/nodes.json), Namen, Adressen, Tokens
  nodes_pair.py   Kopplung mit Bestätigung, Entkoppeln
  nodes_scan.py   Rechner im Netz finden
  cluster.py      Abfrage der Rechner, Proxy, Übergabe
Einstellungen (Namensraum `nodes`): mode (standalone|verbund), discoverable, name, public_url, scan_nets, auto_search.
"""
import asyncio
import ipaddress
import os
import re
import time
import urllib.error
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from app import cluster, ext, nodes_pair, nodes_scan, nodes_store as store
from app.config import PEERS_RAW, VERSION
from app.state import broadcast, peers_state, settings as app_settings

router = APIRouter(prefix="/api/nodes")


class NodesSettings(BaseModel):
    mode: Literal["standalone", "verbund"] = "standalone"
    discoverable: bool = False
    name: str = ""
    public_url: str = ""
    scan_nets: str = ""
    auto_search: bool = False

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return store.clean_name(v)

    @field_validator("public_url")
    @classmethod
    def _url(cls, v: str) -> str:
        return store.norm_url(v) if v.strip() else ""

    @field_validator("scan_nets")
    @classmethod
    def _nets(cls, v: str) -> str:
        parts = [p for p in re.split(r"[,\s]+", v.strip()) if p]
        for p in parts:
            try:
                net = ipaddress.ip_network(p, strict=False)
            except ValueError:
                raise ValueError(f"„{p}“ ist kein Netz (z. B. 192.168.178.0/24)")
            if net.version != 4 or net.prefixlen < 20:
                raise ValueError(f"„{p}“: nur IPv4-Netze bis /20 (höchstens 4096 Adressen)")
        return ", ".join(parts)


def _changed(old: dict, new: dict) -> None:
    if old.get("mode") != new.get("mode") and new.get("mode") != "verbund":
        nodes_pair.incoming.clear()
        nodes_pair.outgoing.clear()
        peers_state.clear()
    broadcast()


ext.register_settings("nodes", NodesSettings, NodesSettings().model_dump(), on_change=_changed)
ext.register_capability("nodes", 1)


# ---------- Statusmeldung
def identity() -> dict:
    """Leicht: wird von anderen Rechnern mitgelesen (Name, Betriebsart, Hardware)."""
    c = store.cfg()
    return {"id": store.self_id(), "name": store.self_name(), "mode": c["mode"], "discoverable": bool(c["discoverable"] and c["mode"] == "verbund"),
            "version": VERSION, "started": store.STARTED, "cores": os.cpu_count() or 1, "mem": store.mem_total()}


def manager() -> dict:
    """Für die eigene Oberfläche: Rechnerliste (ohne Tokens), offene Kopplungsanfragen, Suchergebnisse."""
    return {"nodes": [store.public(n) for n in store.nodes()], "pairing": nodes_pair.snapshot(), "scan": nodes_scan.snapshot(),
            "env_peers": bool(PEERS_RAW.strip())}


ext.register_snapshot("node", identity)
ext.register_snapshot("nodemgr", manager)


# ---------- Prüfen einer Adresse
async def probe_url(url: str) -> dict:
    t = time.time()
    try:
        d = await asyncio.to_thread(cluster._http_json, url + "/api/state", None, 4.0, store.token_for_url(url))
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": "Passwortgeschützt (HTTP 401): erst koppeln, falls dort die neue Version läuft." if e.code == 401 else f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"keine Antwort ({type(e).__name__}: {e})"[:160]}
    if not (isinstance(d.get("drives"), list) and isinstance(d.get("output"), dict)):
        return {"ok": False, "error": "Unter dieser Adresse läuft kein MakeMKV-Web."}
    caps, node = d.get("capabilities") or {}, d.get("node") or {}
    return {"ok": True, "ms": round((time.time() - t) * 1000), "id": node.get("id", ""), "name": node.get("name") or (d.get("capacity") or {}).get("instance", ""),
            "version": caps.get("version", ""), "legacy": not caps.get("nodes"), "mode": node.get("mode", ""),
            "self": bool(node.get("id") and node["id"] == store.self_id())}


class UrlReq(BaseModel):
    url: str
    name: str = ""


def _need_active() -> None:
    if not store.active():
        raise HTTPException(409, "Im eigenständigen Betrieb gibt es keine Rechnerliste.")


@router.get("")
def api_list():
    return {"self": identity(), **manager()}


@router.post("/check")
async def api_check(req: UrlReq):
    """„Prüfen“ vor dem Hinzufügen: erreichbar? alte oder neue Version? schon in der Liste?"""
    url = store.norm_url(req.url)
    if not url:
        raise HTTPException(422, "Ungültige Adresse.")
    r = await probe_url(url)
    known = store.by_url(url) or (store.by_remote_id(r.get("id", "")) if r.get("ok") else None)
    return {**r, "url": url, "known": known["name"] if known else ""}


@router.post("")
async def api_add(req: UrlReq):
    """Rechner ohne Kopplung hinzufügen – nur für alte Versionen, die keine Kopplung kennen. Neue werden über /api/nodes/pair gekoppelt."""
    _need_active()
    url = store.norm_url(req.url)
    if not url:
        raise HTTPException(422, "Ungültige Adresse.")
    if store.by_url(url):
        raise HTTPException(409, "Dieser Rechner ist schon in der Liste.")
    r = await probe_url(url)
    if not r["ok"]:
        raise HTTPException(502, r["error"])
    if r["self"]:
        raise HTTPException(400, "Das ist dieser Rechner.")
    if not r["legacy"]:
        raise HTTPException(409, "Dieser Rechner kennt die Kopplung – bitte „Kopplung anfragen“ verwenden.")
    n = store.add(req.name or r["name"] or url_host_name(url), url, "manual")
    broadcast()
    return store.public(n)


def url_host_name(url: str) -> str:
    return store.url_host(url) or "rechner"


class RenameReq(BaseModel):
    name: str


def _get(nid: str) -> dict:
    n = store.by_nid(nid)
    if not n:
        raise HTTPException(404, "Rechner nicht in der Liste.")
    return n


@router.patch("/{nid}")
def api_rename(nid: str, req: RenameReq):
    n = _get(nid)
    name = store.clean_name(req.name)
    if not name:
        raise HTTPException(422, "Der Name darf nicht leer sein (keine Zeichen / \\ ? # % ,).")
    if name.lower() != n["name"].lower() and store.unique_name(name, skip_nid=nid) != name:
        raise HTTPException(409, "Dieser Name ist schon vergeben.")
    peers_state.pop(n["name"], None)
    n["name"] = name
    store.save()
    broadcast()
    return store.public(n)


@router.delete("/{nid}")
async def api_remove(nid: str):
    n = _get(nid)
    await nodes_pair.notify_unpair(n)
    store.remove(n)
    broadcast()
    return {"ok": True}


@router.post("/{nid}/unpair")
async def api_unpair(nid: str):
    n = _get(nid)
    await nodes_pair.notify_unpair(n)
    n.update(token="", trust="legacy")
    store.save()
    broadcast()
    return store.public(n)


@router.post("/{nid}/test")
async def api_test(nid: str):
    n = _get(nid)
    return await probe_url(n["url"])


ext.register_router(router)


# ---------- Start: Liste laden, PEERS übernehmen, Abfrage starten
async def startup():
    existed = store.load()
    peers = cluster.parse_peers(PEERS_RAW)
    added = False
    for name, url in peers.items():
        url = store.norm_url(url)
        if url and url not in store.data["env_seen"]:
            store.data["env_seen"].append(url)
            if not store.by_url(url):
                store.add(name, url, "peers")
                added = True
    if not existed or added:
        store.save()
    if not existed and added and store.cfg()["mode"] == "standalone":
        # Erster Start mit diesem Stand und PEERS gesetzt: der Rechner war bisher im Verbund und bleibt es.
        app_settings["nodes"] = {**store.cfg(), "mode": "verbund"}
        from app.settings import save_settings
        save_settings()
    await cluster.peer_prober()


ext.register_startup(startup)
