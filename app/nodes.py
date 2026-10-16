"""Machine management (package C): mode, own identity, machine list, connection test.

This module is loaded automatically by main.py (OPTIONAL_MODULES) and registers via app.ext. The parts:
  nodes_store.py  machine list (DATA/nodes.json), names, addresses, tokens
  nodes_pair.py   pairing with confirmation, unpairing
  nodes_scan.py   finding machines on the network
  cluster.py      polling the machines, proxy, hand-over
Settings (namespace `nodes`): mode (verbund = cluster | standalone), pairing_required, name, public_url, scan_nets, auto_search.
Default: cluster mode, always discoverable, pairing with a token optional (pairing_required=False: machines can be added directly).
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
    mode: Literal["standalone", "verbund"] = "verbund"
    pairing_required: bool = False
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
                raise ValueError(f"\"{p}\" is not a network (e.g. 192.168.178.0/24)")
            if net.version != 4 or net.prefixlen < 20:
                raise ValueError(f"\"{p}\": only IPv4 networks up to /20 (at most 4096 addresses)")
        return ", ".join(parts)


def _changed(old: dict, new: dict) -> None:
    if old.get("mode") != new.get("mode") and new.get("mode") != "verbund":
        nodes_pair.incoming.clear()
        nodes_pair.outgoing.clear()
        peers_state.clear()
    broadcast()


ext.register_settings("nodes", NodesSettings, NodesSettings().model_dump(), on_change=_changed)
ext.register_capability("nodes", 1)


# ---------- state report
def identity() -> dict:
    """Lightweight: read by other machines (name, mode, hardware)."""
    c = store.cfg()
    return {"id": store.self_id(), "name": store.self_name(), "mode": c["mode"], "discoverable": c["mode"] == "verbund",
            "version": VERSION, "started": store.STARTED, "cores": os.cpu_count() or 1, "mem": store.mem_total()}


def manager() -> dict:
    """For our own interface: machine list (without tokens), open pairing requests, search results."""
    return {"nodes": [store.public(n) for n in store.nodes()], "pairing": nodes_pair.snapshot(), "scan": nodes_scan.snapshot(),
            "env_peers": bool(PEERS_RAW.strip())}


ext.register_snapshot("node", identity)
ext.register_snapshot("nodemgr", manager)


# ---------- checking an address
async def probe_url(url: str) -> dict:
    t = time.time()
    try:
        d = await asyncio.to_thread(cluster._http_json, url + "/api/state", None, 4.0, store.token_for_url(url))
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": "Password protected (HTTP 401): pair first if the new version runs there." if e.code == 401 else f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"no response ({type(e).__name__}: {e})"[:160]}
    if not (isinstance(d.get("drives"), list) and isinstance(d.get("output"), dict)):
        return {"ok": False, "error": "There is no Spindle running at this address."}
    caps, node = d.get("capabilities") or {}, d.get("node") or {}
    return {"ok": True, "ms": round((time.time() - t) * 1000), "id": node.get("id", ""), "name": node.get("name") or (d.get("capacity") or {}).get("instance", ""),
            "version": caps.get("version", ""), "legacy": not caps.get("nodes"), "mode": node.get("mode", ""),
            "self": bool(node.get("id") and node["id"] == store.self_id())}


class UrlReq(BaseModel):
    url: str
    name: str = ""


def _need_active() -> None:
    if not store.active():
        raise HTTPException(409, "In standalone mode there is no machine list.")


@router.get("")
def api_list():
    return {"self": identity(), **manager()}


@router.post("/check")
async def api_check(req: UrlReq):
    """The "check" before adding: reachable? old or new version? already in the list?"""
    url = store.norm_url(req.url)
    if not url:
        raise HTTPException(422, "Invalid address.")
    r = await probe_url(url)
    known = store.by_url(url) or (store.by_remote_id(r.get("id", "")) if r.get("ok") else None)
    return {**r, "url": url, "known": known["name"] if known else ""}


@router.post("")
async def api_add(req: UrlReq):
    """Add a machine without pairing: always allowed for old versions; for new ones only while pairing is not required (pairing_required)."""
    _need_active()
    url = store.norm_url(req.url)
    if not url:
        raise HTTPException(422, "Invalid address.")
    if store.by_url(url):
        raise HTTPException(409, "This machine is already in the list.")
    r = await probe_url(url)
    if not r["ok"]:
        raise HTTPException(502, r["error"])
    if r["self"]:
        raise HTTPException(400, "That is this machine.")
    if not r["legacy"] and store.cfg()["pairing_required"]:
        raise HTTPException(409, "Pairing is required – please use \"Request pairing\".")
    n = store.add(req.name or r["name"] or url_host_name(url), url, "manual")
    broadcast()
    return store.public(n)


def url_host_name(url: str) -> str:
    return store.url_host(url) or "machine"


class RenameReq(BaseModel):
    name: str


def _get(nid: str) -> dict:
    n = store.by_nid(nid)
    if not n:
        raise HTTPException(404, "Machine not in the list.")
    return n


@router.patch("/{nid}")
def api_rename(nid: str, req: RenameReq):
    n = _get(nid)
    name = store.clean_name(req.name)
    if not name:
        raise HTTPException(422, "The name must not be empty (no characters / \\ ? # % ,).")
    if name.lower() != n["name"].lower() and store.unique_name(name, skip_nid=nid) != name:
        raise HTTPException(409, "This name is already taken.")
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


# ---------- startup: load the list, take over PEERS, start polling
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
        # First start with this version and PEERS set: the machine was in the cluster before and stays there.
        app_settings["nodes"] = {**store.cfg(), "mode": "verbund"}
        from app.settings import save_settings
        save_settings()
    await cluster.peer_prober()


ext.register_startup(startup)
