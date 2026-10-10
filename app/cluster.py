"""Verbund: andere Rechner abfragen, Aktionen weiterleiten, Konvertierungen übergeben.

Die Rechnerliste kommt aus app/nodes_store.py (DATA/nodes.json); jeder Rechner wird von einer eigenen Aufgabe abgefragt, damit
ein ausgefallener Rechner die anderen nicht aufhält. Gekoppelte Rechner tragen bei jedem Aufruf das Token (`X-Node-Token`).
"""
import asyncio
import json
import re
import time
from pathlib import Path
import urllib.error
import urllib.request

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from app import convert, ext, nodes_store as store
from app.config import INSTANCE
from app.files import held_locks
from app.state import CV_ACTIVE, broadcast, conversions, drives, peers_state


router = APIRouter()
PEER_POLL_S = 3.0
WHOAMI_S = 30.0         # so oft prüft ein gekoppelter Rechner, ob die Gegenseite die Kopplung noch kennt


def parse_peers(raw: str) -> dict[str, str]:
    """Umgebungsvariable PEERS („name=http://host:8780,…“) – nur noch Vorbelegung der Rechnerliste (Migration)."""
    out: dict[str, str] = {}
    for part in raw.split(","):
        name, _, url = part.strip().partition("=")
        name, url = name.strip(), url.strip().rstrip("/")
        if name and re.fullmatch(r"https?://[A-Za-z0-9.\-\[\]:]+", url) and name.lower() != INSTANCE.lower():
            out[name] = url
    return out


def _http_json(url: str, body: dict | None = None, timeout: float = 4.0, token: str = ""):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Node-Token"] = token
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers=headers, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def _peer_json(base_url: str, path: str, body: dict | None = None, timeout: float = 4.0):
    """Aufruf eines Rechners der Liste (mit seinem Token, falls gekoppelt). `path` ohne /api/."""
    return _http_json(f"{base_url}/api/{path}", body, timeout, store.token_for_url(base_url))


def _http_detail(e: urllib.error.HTTPError) -> str:
    try:
        return json.loads(e.read()).get("detail", str(e))
    except (ValueError, AttributeError):
        return str(e)


async def peer_call(name: str, path: str, body: dict | None = None, timeout: float = 15.0):
    """Für andere Module: `await cluster.peer_call("maintux", "library/convert", {...})`. Wirft HTTPException bei Fehlern."""
    n = store.by_name(name)
    if not n or not store.active():
        raise HTTPException(404, f"Rechner {name} ist nicht in der Liste.")
    try:
        return await asyncio.to_thread(_http_json, f"{n['url']}/api/{path}", body if body is not None else {}, timeout, n["token"])
    except urllib.error.HTTPError as e:
        raise HTTPException(e.code, _http_detail(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"{name} antwortet nicht: {e}")


def _trust(n: dict, lost: bool) -> str:
    return "lost" if lost else ("paired" if n.get("token") else "legacy")


def _entry(n: dict, d: dict, old: dict | None, lost: bool) -> dict:
    cap = d.get("capacity") or {}
    caps = d.get("capabilities") or {}
    node = d.get("node") or {}
    jobs = [{"dev": x.get("dev"), "name": x.get("name"), "kind": x["job"].get("kind"), "title": x["job"].get("title") or (x.get("disc") or {}).get("name") or "",
             "overall": x["job"].get("overall", 0), "total": x["job"].get("total", 0), "bytes": x["job"].get("bytes", 0), "index": x["job"].get("index", 0), "count": x["job"].get("count", 0), "text": x["job"].get("text", ""), "started": x["job"].get("started", 0)}
            for x in d.get("drives", []) if isinstance(x, dict) and x.get("job")]
    reachable = isinstance(d.get("drives"), list) and isinstance(d.get("output"), dict)
    now = time.time()
    return {"name": n["name"], "url": n["url"], "reachable": reachable,
            "instance": cap.get("instance", n["name"]), "cores": cap.get("cores", 0), "load": cap.get("load", 0), "conv_active": cap.get("conv_active", 0),
            "conv_paused": cap.get("conv_paused", False), "has_handover": bool(cap), "now": d.get("now", 0),
            "conversions": d.get("conversions", []), "uploads": d.get("uploads", []), "jobs": jobs,
            "drives": d.get("drives", []), "output": d.get("output"),          # Laufwerke samt Disc/Titeln/Protokoll: für die Fernsteuerung
            "capabilities": caps,
            # Paket C: Identität, Vertrauen, Version
            "nid": n["nid"], "id": node.get("id") or n.get("id", ""), "trust": _trust(n, lost),
            "legacy": not caps.get("nodes"), "version": caps.get("version", ""), "mem": node.get("mem", 0), "started": node.get("started", 0),
            "last_seen": now, "online_since": (old or {}).get("online_since") if (old or {}).get("reachable") else now,
            "id_mismatch": bool(n.get("id") and node.get("id") and n["id"] != node["id"])}


def _offline(n: dict, old: dict | None, lost: bool) -> dict:
    base = old or {"cores": 0, "load": 0, "conv_active": 0, "conv_paused": False, "has_handover": False, "now": 0, "conversions": [], "uploads": [],
                   "jobs": [], "drives": [], "output": None, "capabilities": {}, "instance": n["name"], "legacy": True, "version": "", "mem": 0,
                   "started": 0, "last_seen": 0, "online_since": 0, "id": n.get("id", ""), "id_mismatch": False}
    return {**base, "name": n["name"], "url": n["url"], "reachable": False, "nid": n["nid"], "trust": _trust(n, lost)}


async def _whoami(n: dict):
    """True/False: Gegenseite kennt unser Token (nicht); None: unklar (alter Rechner, Fehler)."""
    try:
        r = await asyncio.to_thread(_http_json, n["url"] + "/api/nodes/whoami", None, 4.0, n["token"])
        return bool(r.get("paired"))
    except Exception:  # noqa: BLE001
        return None


async def _poll_node(nid: str):
    last_name, who_t, lost, misses = None, 0.0, False, 0
    while True:
        n = store.by_nid(nid)
        if not n:
            return
        if last_name and last_name != n["name"]:
            peers_state.pop(last_name, None)
        last_name = n["name"]
        old = peers_state.get(n["name"])
        if n.get("token") and time.time() - who_t > (WHOAMI_S if not misses else 6.0):
            who_t, w = time.time(), await _whoami(n)
            if w is False:          # erst nach zwei Fehlschlägen: direkt nach dem Koppeln kennt die Gegenseite das Token evtl. noch nicht
                misses += 1
                lost = misses >= 2
            elif w:
                misses, lost = 0, False
        elif not n.get("token"):
            misses, lost = 0, False
        try:
            d = await asyncio.to_thread(_http_json, n["url"] + "/api/state", None, 4.0, n.get("token", ""))
            entry = _entry(n, d, old, lost)
            if entry["id"] and not n.get("id"):
                n["id"] = entry["id"]
                store.save()
        except Exception:  # noqa: BLE001
            entry = _offline(n, old, lost)
        strip = lambda x: json.dumps({k: v for k, v in (x or {}).items() if k != "last_seen"}, sort_keys=True, default=str)  # noqa: E731
        if strip(entry) != strip(old):
            peers_state[n["name"]] = entry
            broadcast()
        elif old is not None:
            old["last_seen"] = entry["last_seen"]
        await asyncio.sleep(PEER_POLL_S)


_tasks: dict[str, asyncio.Task] = {}
_running = False


async def peer_prober():
    """Überwacht die Rechnerliste und startet/beendet je Rechner eine Abfrage-Aufgabe. Läuft höchstens einmal."""
    global _running
    if _running:
        return
    _running = True
    while True:
        want = {n["nid"] for n in store.nodes()} if (store.loaded and store.active()) else set()
        for nid in list(_tasks):
            if nid not in want or _tasks[nid].done():
                _tasks.pop(nid).cancel()
        for nid in want - set(_tasks):
            _tasks[nid] = asyncio.create_task(_poll_node(nid))
        names = {n["name"] for n in store.nodes()} if want else set()
        stale = [k for k in peers_state if k not in names]
        for k in stale:
            peers_state.pop(k, None)
        if stale:
            broadcast()
        await asyncio.sleep(1)


async def hand_to_peer_after_upload(item: dict, base: Path, dr):
    """Übergabe einer frisch ins NAS übertragenen Datei: der andere Rechner konvertiert sie als Bibliotheks-Auftrag."""
    t = item["then_convert"]
    try:
        rel = str(Path(item["dest"]).relative_to(base.resolve())) if item.get("dest") else item["name"]
        r = await asyncio.to_thread(_peer_json, t["url"], "library/convert", {"paths": [rel], "convert": t["cfg"]}, 15.0)
        ok_ = rel in r.get("started", [])
        msg = f"Zur Konvertierung an {t['name']} übergeben: {rel}" if ok_ else f"{t['name']} hat {rel} nicht angenommen: {r.get('skipped')}"
        if dr:
            dr.add_log(msg, "ok" if ok_ else "error")
        if not ok_:
            item["error"] = msg
    except Exception as e:  # noqa: BLE001
        item["error"] = f"Übergabe an {t['name']} fehlgeschlagen: {e}"
        if dr:
            dr.add_log(item["error"] + " – die Datei liegt unverändert im Ziel (Bibliothek → konvertieren).", "error")


@router.post("/api/peer/{name}/{pfad:path}")
async def api_peer_proxy(name: str, pfad: str, request: Request):
    """Aktion auf einem anderen Rechner auslösen (der Browser spricht nur mit diesem Server)."""
    peer = peers_state.get(name)
    if not peer or not peer.get("reachable"):
        raise HTTPException(409, f"{name} ist nicht erreichbar.")
    if not ext.proxy_ok(pfad):
        raise HTTPException(404, "Diese Aktion lässt sich nicht an einen anderen Rechner weiterleiten.")
    raw = await request.body()
    body = json.loads(raw) if raw else {}
    if not isinstance(body, dict):
        raise HTTPException(400, "Ungültige Anfrage")
    return await peer_call(name, pfad, body, 30.0)


class HandoverReq(BaseModel):
    target: str


@router.post("/api/handover")
async def api_handover(req: HandoverReq):
    peer = peers_state.get(req.target)
    if not peer or not peer.get("reachable"):
        raise HTTPException(409, f"{req.target} ist nicht erreichbar.")
    if not peer.get("has_handover"):
        raise HTTPException(409, f"{req.target} läuft noch mit einer älteren Version ohne Übergabe – dort zuerst aktualisieren.")
    if any(d.job for d in drives.values()):
        raise HTTPException(409, "Ein Rip, Backup oder eine Analyse läuft – das Laufwerk hängt an diesem Rechner. Erst abwarten oder abbrechen.")
    handed, errors = [], []
    for c in [c for c in conversions if c["status"] in CV_ACTIVE]:
        label = c["name"]
        if c.get("origin") == "library":
            # Der andere Rechner übernimmt die Sperre (gleicher Besitzer), ich gebe sie nur auf, ohne die Datei freizugeben.
            try:
                r = await asyncio.to_thread(_peer_json, peer["url"], "library/convert",
                                            {"paths": [c["rel"]], "convert": c["cfg"], "takeover_from": INSTANCE}, 15.0)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{label}: {e}")
                continue
            if c["rel"] not in r.get("started", []):
                errors.append(f"{label}: {r.get('skipped')}")
                continue
            held_locks.discard(c["lock"])
            c["lock"] = ""
        else:
            c["handover"] = {"url": peer["url"], "name": req.target}     # Original geht erst ins NAS, dann zum anderen Rechner
        c["handed"] = req.target
        convert.skip_conversion(c)
        handed.append(label)
    broadcast()
    return {"ok": not errors, "handed": handed, "errors": errors, "target": req.target}
