"""Verbund: andere Rechner abfragen, Aktionen weiterleiten, Konvertierungen übergeben."""
import asyncio
import json
import re
from pathlib import Path
import urllib.error
import urllib.request

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from app import convert, ext
from app.config import INSTANCE, PEERS_RAW
from app.files import held_locks
from app.state import CV_ACTIVE, broadcast, conversions, drives, peers_state


router = APIRouter()


def parse_peers(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in raw.split(","):
        name, _, url = part.strip().partition("=")
        name, url = name.strip(), url.strip().rstrip("/")
        if name and re.fullmatch(r"https?://[A-Za-z0-9.\-\[\]:]+", url) and name.lower() != INSTANCE.lower():
            out[name] = url
    return out


def _http_json(url: str, body: dict | None = None, timeout: float = 4.0):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


PEER_POLL_S = 3.0


def _peer_entry(name: str, url: str, d: dict) -> dict:
    cap = d.get("capacity") or {}
    jobs = [{"dev": x.get("dev"), "name": x.get("name"), "kind": x["job"].get("kind"), "title": x["job"].get("title") or (x.get("disc") or {}).get("name") or "",
             "overall": x["job"].get("overall", 0), "total": x["job"].get("total", 0), "bytes": x["job"].get("bytes", 0), "index": x["job"].get("index", 0), "count": x["job"].get("count", 0), "text": x["job"].get("text", ""), "started": x["job"].get("started", 0)}
            for x in d.get("drives", []) if isinstance(x, dict) and x.get("job")]
    return {"name": name, "url": url, "reachable": isinstance(d.get("drives"), list) and isinstance(d.get("output"), dict),
            "instance": cap.get("instance", name), "cores": cap.get("cores", 0), "load": cap.get("load", 0), "conv_active": cap.get("conv_active", 0),
            "conv_paused": cap.get("conv_paused", False), "has_handover": bool(cap), "now": d.get("now", 0),
            "conversions": d.get("conversions", []), "uploads": d.get("uploads", []), "jobs": jobs,
            "drives": d.get("drives", []), "output": d.get("output"),
            "capabilities": d.get("capabilities") or {}}      # Laufwerke samt Disc/Titeln/Protokoll: für die Fernsteuerung


async def peer_prober():
    peers = parse_peers(PEERS_RAW)
    while True:
        changed = False
        for name, url in peers.items():
            try:
                d = await asyncio.to_thread(_http_json, url + "/api/state")
                entry = _peer_entry(name, url, d)
            except Exception:  # noqa: BLE001
                entry = {**peers_state.get(name, {}), "name": name, "url": url, "reachable": False}
            if json.dumps(entry, sort_keys=True, default=str) != json.dumps(peers_state.get(name), sort_keys=True, default=str):
                peers_state[name] = entry
                changed = True
        if changed:
            broadcast()
        await asyncio.sleep(PEER_POLL_S)


async def hand_to_peer_after_upload(item: dict, base: Path, dr):
    """Übergabe einer frisch ins NAS übertragenen Datei: der andere Rechner konvertiert sie als Bibliotheks-Auftrag."""
    t = item["then_convert"]
    try:
        rel = str(Path(item["dest"]).relative_to(base.resolve())) if item.get("dest") else item["name"]
        r = await asyncio.to_thread(_http_json, t["url"] + "/api/library/convert", {"paths": [rel], "convert": t["cfg"]}, 15.0)
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
    try:
        return await asyncio.to_thread(_http_json, f"{peer['url']}/api/{pfad}", body, 30.0)
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("detail", str(e))
        except (ValueError, AttributeError):
            detail = str(e)
        raise HTTPException(e.code, detail)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"{name} antwortet nicht: {e}")


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
                r = await asyncio.to_thread(_http_json, peer["url"] + "/api/library/convert",
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
