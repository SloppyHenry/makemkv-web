"""Pairing two machines with confirmation and a shared token.

Flow (A requests, B confirms):
  1. A -> B  POST /api/nodes/pair-request   (A sends name, address and a secret, B answers with a request number and a code)
  2. B shows "A wants to connect" with the code; the user confirms or declines
  3. A polls B regularly (GET /api/nodes/pair-poll/<no>, secret in the header) and receives the token after confirmation
  4. both add the other one with the token; from now on each sends `X-Node-Token` on calls
Open requests only live in memory and expire after 10 minutes. The token is transferred unencrypted (HTTP) in the LAN;
that protects against foreign calls when a password is set, not against eavesdropping on the same network.
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
incoming: dict[str, dict] = {}       # requests from other machines to us
outgoing: dict[str, dict] = {}       # our requests to others

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
    """Another machine wants to pair (reachable without login; only takes effect after the user confirms)."""
    if not store.active():
        raise HTTPException(403, "This machine works standalone and does not accept pairing requests.")
    if not req.id or req.id == store.self_id():
        raise HTTPException(400, "That is the same machine.")
    url = store.norm_url(req.url)
    if not url or len(req.secret) < 16:
        raise HTTPException(422, "Invalid request.")
    if store.is_loopback(store.url_host(url)) and request.client and not store.is_loopback(request.client.host):
        url = url.replace(store.url_host(url), request.client.host, 1)      # the other one calls itself "localhost": use the sender
    _purge()
    for rid in [r for r, i in incoming.items() if i["id"] == req.id]:
        incoming.pop(rid)
    if sum(1 for i in incoming.values() if i["status"] == "pending") >= MAX_PENDING:
        raise HTTPException(429, "Too many open pairing requests.")
    rid, code = secrets.token_hex(8), f"{secrets.randbelow(10**6):06d}"
    incoming[rid] = {"id": req.id, "name": store.clean_name(req.name) or "unnamed", "url": url, "version": req.version[:20], "code": code,
                     "secret": _h(req.secret), "ts": time.time(), "status": "pending", "token": ""}
    broadcast()
    return {"rid": rid, "code": code, "id": store.self_id(), "name": store.self_name(), "version": VERSION}


@router.get("/pair-poll/{rid}")
def pair_poll(rid: str, request: Request):
    inc = incoming.get(rid)
    if not inc or not hmac.compare_digest(inc["secret"], _h(request.headers.get("x-pair-secret", ""))):
        raise HTTPException(404, "Request unknown or expired.")
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
        raise HTTPException(404, "The request has expired or was withdrawn.")
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


# ---------- our request to another machine
class PairStart(BaseModel):
    url: str


def own_url(request: Request) -> str:
    c = store.cfg()
    return store.norm_url(c["public_url"]) if c["public_url"] else f"{request.url.scheme}://{request.headers.get('host', '')}"


@router.post("/pair")
async def pair_start(req: PairStart, request: Request):
    if not store.active():
        raise HTTPException(409, "In standalone mode there is no pairing.")
    url = store.norm_url(req.url)
    if not url:
        raise HTTPException(422, "Invalid address.")
    known = store.by_url(url)
    if any(o["url"] == url and o["status"] == "waiting" for o in outgoing.values()):
        raise HTTPException(409, "A request for this machine is already running.")
    if known and known.get("token") and (peers_state.get(known["name"]) or {}).get("trust") != "lost":
        raise HTTPException(409, "This machine is already paired.")
    secret = secrets.token_urlsafe(24)
    body = {"id": store.self_id(), "name": store.self_name(), "url": own_url(request), "version": VERSION, "secret": secret}
    try:
        r = await asyncio.to_thread(_http_json, url + "/api/nodes/pair-request", body, 6.0)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise HTTPException(409, "An older version without pairing runs there. Add the machine without pairing.")
        raise HTTPException(e.code, _http_detail(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"{url} does not respond: {e}")
    if r.get("id") == store.self_id():
        raise HTTPException(400, "That is this machine.")
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
                o.update(status="expired", error="The request expired on the other machine.")
                break
            except Exception:  # noqa: BLE001
                continue                    # briefly unreachable: keep waiting
            if r.get("status") == "denied":
                o.update(status="denied", error="The other machine declined the pairing.")
            elif r.get("status") == "accepted" and r.get("token"):
                n = store.by_remote_id(r.get("id", "")) or store.by_url(o["url"])
                if n:
                    n.update(token=r["token"], trust="paired", id=r.get("id", n.get("id", "")))
                    store.save()
                else:
                    store.add(r.get("name") or o["name"], o["url"], "pairing", r.get("id", ""), r["token"])
                o["status"] = "ok"
        if o["status"] == "waiting":
            o.update(status="expired", error="No answer within 10 minutes.")
    finally:
        o["done"] = time.time()
        broadcast()


@router.post("/pair-outgoing/{rid}/cancel")
async def pair_withdraw(rid: str):
    o = outgoing.get(rid)
    if not o or o["status"] != "waiting":
        raise HTTPException(404, "No open request.")
    o.update(status="cancelled", error="Withdrawn.", done=time.time())
    try:
        await asyncio.to_thread(_http_json, f"{o['url']}/api/nodes/pair-cancel/{o['remote_rid']}", {"secret": o["secret"]}, 4.0)
    except Exception:  # noqa: BLE001
        pass
    broadcast()
    return {"ok": True}


# ---------- unpairing and cross-check
@router.post("/unpair")
def unpair_by_peer(request: Request):
    """The other machine dissolves the pairing (token in the header)."""
    n = store.node_for_token(request.headers.get("x-node-token", ""))
    if not n:
        raise HTTPException(401, "Not paired.")
    n.update(token="", trust="legacy")
    store.save()
    broadcast()
    return {"ok": True}


@router.get("/whoami")
def whoami(request: Request):
    """Does this machine know the token that was sent along? Only then does it reveal name and id."""
    if store.node_for_token(request.headers.get("x-node-token", "")):
        return {"paired": True, "id": store.self_id(), "name": store.self_name()}
    return {"paired": False}


async def notify_unpair(n: dict) -> None:
    """Notify the other side (best effort; if it is offline, it notices later via whoami)."""
    if not n.get("token"):
        return
    try:
        await asyncio.to_thread(_http_json, n["url"] + "/api/nodes/unpair", {}, 4.0, n["token"])
    except Exception:  # noqa: BLE001
        pass


ext.register_router(router)
