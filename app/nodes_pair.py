"""Kopplung zweier Rechner mit Bestätigung und gemeinsamem Token.

Ablauf (A fragt an, B bestätigt):
  1. A -> B  POST /api/nodes/pair-request   (A schickt Name, Adresse und ein Geheimnis, B antwortet mit Anfrage-Nr. und Code)
  2. B zeigt „A möchte sich verbinden“ mit dem Code; der Nutzer bestätigt oder lehnt ab
  3. A fragt B regelmäßig (GET /api/nodes/pair-poll/<nr>, Geheimnis im Kopf) und erhält nach der Bestätigung das Token
  4. beide tragen den anderen mit dem Token ein; ab jetzt sendet jeder bei Aufrufen `X-Node-Token`
Offene Anfragen liegen nur im Speicher und verfallen nach 10 Minuten. Das Token wird im LAN unverschlüsselt (HTTP) übertragen;
das schützt vor fremden Aufrufen bei gesetztem Passwort, nicht vor Mitlesen im selben Netz.
"""
import asyncio
import hashlib
import hmac
import secrets
import time
import urllib.error
import urllib.request
import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import auth, ext, nodes_store as store
from app.cluster import _http_detail, _http_json
from app.config import VERSION
from app.state import broadcast, peers_state

router = APIRouter(prefix="/api/nodes")
TTL = 600.0
MAX_PENDING = 5
incoming: dict[str, dict] = {}       # Anfragen anderer Rechner an uns
outgoing: dict[str, dict] = {}       # unsere Anfragen an andere

auth.allow_public(r"/api/nodes/(pair-request|pair-poll/[0-9a-f]+|pair-cancel/[0-9a-f]+|whoami)")
auth.register_token_checker(store.token_ok)


def _h(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _purge() -> None:
    now = time.time()
    for rid in [r for r, i in incoming.items() if now - i["ts"] > TTL]:
        incoming.pop(rid, None)
    for rid in [r for r, o in outgoing.items() if o["status"] != "waiting" and now - o["done"] > 60]:
        outgoing.pop(rid, None)


def snapshot() -> dict:
    _purge()
    now = time.time()
    return {"incoming": [{"rid": r, "name": i["name"], "url": i["url"], "version": i["version"], "code": i["code"], "age": int(now - i["ts"])}
                         for r, i in incoming.items() if i["status"] == "pending"],
            "outgoing": [{"rid": r, "url": o["url"], "name": o["name"], "code": o["code"], "status": o["status"], "error": o["error"], "age": int(now - o["ts"])}
                         for r, o in outgoing.items()]}


class PairReq(BaseModel):
    id: str
    name: str
    url: str
    version: str = ""
    secret: str


@router.post("/pair-request")
def pair_request(req: PairReq, request: Request):
    """Ein anderer Rechner will sich koppeln (ohne Anmeldung erreichbar; wirkt erst nach Bestätigung durch den Nutzer)."""
    if not store.active():
        raise HTTPException(403, "Dieser Rechner arbeitet eigenständig und nimmt keine Kopplungsanfragen an.")
    if not req.id or req.id == store.self_id():
        raise HTTPException(400, "Das ist derselbe Rechner.")
    url = store.norm_url(req.url)
    if not url or len(req.secret) < 16:
        raise HTTPException(422, "Ungültige Anfrage.")
    if store.is_loopback(store.url_host(url)) and request.client and not store.is_loopback(request.client.host):
        url = url.replace(store.url_host(url), request.client.host, 1)      # der andere nennt sich „localhost“: Absender nehmen
    _purge()
    for rid in [r for r, i in incoming.items() if i["id"] == req.id]:
        incoming.pop(rid)
    if sum(1 for i in incoming.values() if i["status"] == "pending") >= MAX_PENDING:
        raise HTTPException(429, "Zu viele offene Kopplungsanfragen.")
    rid, code = secrets.token_hex(8), f"{secrets.randbelow(10**6):06d}"
    incoming[rid] = {"id": req.id, "name": store.clean_name(req.name) or "unbenannt", "url": url, "version": req.version[:20], "code": code,
                     "secret": _h(req.secret), "ts": time.time(), "status": "pending", "token": ""}
    broadcast()
    return {"rid": rid, "code": code, "id": store.self_id(), "name": store.self_name(), "version": VERSION}


@router.get("/pair-poll/{rid}")
def pair_poll(rid: str, request: Request):
    inc = incoming.get(rid)
    if not inc or not hmac.compare_digest(inc["secret"], _h(request.headers.get("x-pair-secret", ""))):
        raise HTTPException(404, "Anfrage unbekannt oder abgelaufen.")
    if inc["status"] == "accepted":
        return {"status": "accepted", "token": inc["token"], "id": store.self_id(), "name": store.self_name()}
    return {"status": inc["status"]}


class SecretReq(BaseModel):
    secret: str


@router.post("/pair-cancel/{rid}")
def pair_cancel(rid: str, req: SecretReq):
    inc = incoming.get(rid)
    if inc and hmac.compare_digest(inc["secret"], _h(req.secret)) and inc["status"] == "pending":
        incoming.pop(rid)
        broadcast()
    return {"ok": True}


@router.post("/pair-incoming/{rid}/accept")
def pair_accept(rid: str):
    inc = incoming.get(rid)
    if not inc or inc["status"] != "pending":
        raise HTTPException(404, "Die Anfrage ist abgelaufen oder wurde zurückgezogen.")
    token = store.new_token()
    n = store.by_remote_id(inc["id"]) or store.by_url(inc["url"])
    if n:
        n.update(token=token, trust="paired", id=inc["id"], url=inc["url"])
        store.save()
    else:
        n = store.add(inc["name"], inc["url"], "pairing", inc["id"], token)
    inc.update(status="accepted", token=token, ts=time.time())
    broadcast()
    return {"ok": True, "node": store.public(n)}


@router.post("/pair-incoming/{rid}/deny")
def pair_deny(rid: str):
    inc = incoming.get(rid)
    if inc and inc["status"] == "pending":
        inc["status"] = "denied"
        broadcast()
    return {"ok": True}


# ---------- unsere Anfrage an einen anderen Rechner
class PairStart(BaseModel):
    url: str


def own_url(request: Request) -> str:
    c = store.cfg()
    return store.norm_url(c["public_url"]) if c["public_url"] else f"{request.url.scheme}://{request.headers.get('host', '')}"


@router.post("/pair")
async def pair_start(req: PairStart, request: Request):
    if not store.active():
        raise HTTPException(409, "Im eigenständigen Betrieb gibt es keine Kopplung.")
    url = store.norm_url(req.url)
    if not url:
        raise HTTPException(422, "Ungültige Adresse.")
    known = store.by_url(url)
    if any(o["url"] == url and o["status"] == "waiting" for o in outgoing.values()):
        raise HTTPException(409, "Für diesen Rechner läuft schon eine Anfrage.")
    if known and known.get("token") and (peers_state.get(known["name"]) or {}).get("trust") != "lost":
        raise HTTPException(409, "Dieser Rechner ist bereits gekoppelt.")
    secret = secrets.token_urlsafe(24)
    body = {"id": store.self_id(), "name": store.self_name(), "url": own_url(request), "version": VERSION, "secret": secret}
    try:
        r = await asyncio.to_thread(_http_json, url + "/api/nodes/pair-request", body, 6.0)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise HTTPException(409, "Dort läuft eine ältere Version ohne Kopplung. Füge den Rechner ohne Kopplung hinzu.")
        raise HTTPException(e.code, _http_detail(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"{url} antwortet nicht: {e}")
    if r.get("id") == store.self_id():
        raise HTTPException(400, "Das ist dieser Rechner.")
    rid = secrets.token_hex(8)
    outgoing[rid] = {"url": url, "name": r.get("name") or url, "code": r.get("code", ""), "status": "waiting", "error": "", "ts": time.time(),
                     "done": 0, "remote_rid": r.get("rid", ""), "secret": secret}
    asyncio.create_task(_wait_for_answer(rid))
    broadcast()
    return {"rid": rid, "code": r.get("code", ""), "name": outgoing[rid]["name"]}


def _get_with_secret(url: str, secret: str):
    req = urllib.request.Request(url, headers={"X-Pair-Secret": secret})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read() or b"{}")


async def _wait_for_answer(rid: str):
    o = outgoing[rid]
    try:
        while o["status"] == "waiting" and time.time() - o["ts"] < TTL:
            await asyncio.sleep(2)
            if o["status"] != "waiting":
                return
            try:
                r = await asyncio.to_thread(_get_with_secret, f"{o['url']}/api/nodes/pair-poll/{o['remote_rid']}", o["secret"])
            except urllib.error.HTTPError:
                o.update(status="expired", error="Die Anfrage ist auf dem anderen Rechner abgelaufen.")
                break
            except Exception:  # noqa: BLE001
                continue                    # kurz nicht erreichbar: weiter warten
            if r.get("status") == "denied":
                o.update(status="denied", error="Der andere Rechner hat die Kopplung abgelehnt.")
            elif r.get("status") == "accepted" and r.get("token"):
                n = store.by_remote_id(r.get("id", "")) or store.by_url(o["url"])
                if n:
                    n.update(token=r["token"], trust="paired", id=r.get("id", n.get("id", "")))
                    store.save()
                else:
                    store.add(r.get("name") or o["name"], o["url"], "pairing", r.get("id", ""), r["token"])
                o["status"] = "ok"
        if o["status"] == "waiting":
            o.update(status="expired", error="Keine Antwort innerhalb von 10 Minuten.")
    finally:
        o["done"] = time.time()
        broadcast()


@router.post("/pair-outgoing/{rid}/cancel")
async def pair_withdraw(rid: str):
    o = outgoing.get(rid)
    if not o or o["status"] != "waiting":
        raise HTTPException(404, "Keine offene Anfrage.")
    o.update(status="cancelled", error="Zurückgezogen.", done=time.time())
    try:
        await asyncio.to_thread(_http_json, f"{o['url']}/api/nodes/pair-cancel/{o['remote_rid']}", {"secret": o["secret"]}, 4.0)
    except Exception:  # noqa: BLE001
        pass
    broadcast()
    return {"ok": True}


# ---------- Entkoppeln und Gegenprobe
@router.post("/unpair")
def unpair_by_peer(request: Request):
    """Der andere Rechner löst die Kopplung (Token im Kopf)."""
    n = store.node_for_token(request.headers.get("x-node-token", ""))
    if not n:
        raise HTTPException(401, "Nicht gekoppelt.")
    n.update(token="", trust="legacy")
    store.save()
    broadcast()
    return {"ok": True}


@router.get("/whoami")
def whoami(request: Request):
    """Kennt dieser Rechner das mitgeschickte Token? Nur dann nennt er Name und Kennung."""
    if store.node_for_token(request.headers.get("x-node-token", "")):
        return {"paired": True, "id": store.self_id(), "name": store.self_name()}
    return {"paired": False}


async def notify_unpair(n: dict) -> None:
    """Gegenseite benachrichtigen (best effort; ist sie offline, merkt sie es später über whoami)."""
    if not n.get("token"):
        return
    try:
        await asyncio.to_thread(_http_json, n["url"] + "/api/nodes/unpair", {}, 4.0, n["token"])
    except Exception:  # noqa: BLE001
        pass


ext.register_router(router)
