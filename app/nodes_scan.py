"""Rechner im Netz finden: aktiver Scan (TCP + GET /api/discovery/hello).

Warum kein mDNS: Multicast/Broadcast kommen im Standard-Bridge-Netz von Docker nicht in den Container; mDNS bräuchte
`network_mode: host` (Port-Zuordnung und Firewall ändern sich, Sache von PZ) und eine zusätzliche Abhängigkeit. Der Scan
funktioniert in jedem Netz, in dem der Container ausgehende Verbindungen darf.

Welche Adressen geprüft werden (Reihenfolge der Quellen):
  1. Umgebungsvariable NODES_SCAN_TARGETS (nur Entwicklung/Test, ersetzt alles andere), z. B. „127.0.0.1:8820-8822“
  2. das /24-Netz der Adresse, unter der der Browser diese Seite aufgerufen hat (im Docker die LAN-Adresse des Hosts)
  3. die /24-Netze bereits eingetragener Rechner
  4. Einstellung `nodes.scan_nets` (CIDR-Liste)
  5. nur wenn nichts davon ein Netz ergibt: die Netze der eigenen Schnittstellen
Ports: 8780, der Port der aufgerufenen Seite und NODES_SCAN_PORTS.
Ein Rechner antwortet nur, wenn bei ihm „auffindbar“ eingeschaltet ist; sonst 404.
"""
import asyncio
import ipaddress
import json
import os
import re
import socket
import time

from fastapi import APIRouter, HTTPException, Request

from app import auth, ext, nodes_store as store
from app.config import FEATURES, INSTANCE, VERSION
from app.state import broadcast

router = APIRouter(prefix="/api/discovery")
auth.allow_public(r"/api/discovery/hello")
MAX_HOSTS = 4096
CONCURRENCY = 96
scan: dict = {"running": False, "done": 0, "total": 0, "found": [], "started": 0, "finished": 0, "nets": [], "error": "", "cancel": False}


@router.get("/hello")
def hello():
    """Antwort auf die Suche. Nur im Verbund und nur, wenn „auffindbar“ an ist; sonst tut der Rechner, als gäbe es das nicht."""
    if not (store.active() and store.cfg()["discoverable"]):
        raise HTTPException(404, "Not found")
    return {"app": "makemkv-web", "id": store.self_id(), "name": store.self_name(), "instance": INSTANCE, "version": VERSION, "features": FEATURES,
            "cores": os.cpu_count() or 1, "mem": store.mem_total(), "pairing": True}


# ---------- Ziele bestimmen
def _ports(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split("+"):
        a, _, b = part.partition("-")
        if a.isdigit():
            out += list(range(int(a), (int(b) if b.isdigit() else int(a)) + 1))
    return [p for p in out if 0 < p < 65536][:64]


def env_targets(raw: str) -> list[tuple[str, int]]:
    """NODES_SCAN_TARGETS: Einträge durch Komma, je „host“, „host:port“, „host:port-port“ oder „a.b.c.d/24[:port]“."""
    out: list[tuple[str, int]] = []
    for item in re.split(r"[,\s]+", raw.strip()):
        if not item:
            continue
        addr, _, ports = item.partition(":")
        plist = _ports(ports.replace(",", "+")) if ports else [store.DEFAULT_PORT]
        try:
            hosts = [str(h) for h in ipaddress.ip_network(addr, strict=False).hosts()] if "/" in addr else [addr]
        except ValueError:
            continue
        out += [(h, p) for h in hosts[:MAX_HOSTS] for p in plist]
    return out[:MAX_HOSTS * 2]


def _net24(host: str):
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    if ip.version != 4 or ip.is_loopback or ip.is_link_local or ip.is_unspecified:
        return None
    return ipaddress.ip_network(f"{ip}/24", strict=False)


def _local_nets() -> list:
    ips: set[str] = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    return [n for n in map(_net24, ips) if n]


def targets(request_host: str = "", request_port: int = 0) -> tuple[list[tuple[str, int]], list[str]]:
    raw = os.environ.get("NODES_SCAN_TARGETS", "")
    if raw.strip():
        t = env_targets(raw)
        return t, [f"{len(t)} Adressen (NODES_SCAN_TARGETS)"]
    nets: list = []
    n = _net24(request_host)
    if n:
        nets.append(n)
    nets += [x for x in (_net24(store.url_host(nd["url"])) for nd in store.nodes()) if x]
    for part in re.split(r"[,\s]+", store.cfg()["scan_nets"].strip()):
        try:
            net = ipaddress.ip_network(part, strict=False) if part else None
        except ValueError:
            net = None
        if net and net.version == 4 and net.prefixlen >= 20:
            nets.append(net)
    if not nets:
        nets = _local_nets()
    uniq = list(dict.fromkeys(nets))
    ports = list(dict.fromkeys([store.DEFAULT_PORT, request_port, *_ports(os.environ.get("NODES_SCAN_PORTS", "").replace(",", "+"))]))
    out = [(str(h), p) for net in uniq for h in net.hosts() for p in ports if p]
    return out[:MAX_HOSTS * 2], [str(n) for n in uniq]


# ---------- Prüfen
async def probe(host: str, port: int, sem: asyncio.Semaphore):
    async with sem:
        w = None
        try:
            r, w = await asyncio.wait_for(asyncio.open_connection(host, port), 0.7)
            w.write(f"GET /api/discovery/hello HTTP/1.0\r\nHost: {host}:{port}\r\nUser-Agent: makemkv-web-scan\r\n\r\n".encode())
            await w.drain()
            raw = b""
            async def _all():
                nonlocal raw
                while len(raw) < 65536:           # Kopf und Inhalt kommen oft in getrennten Stücken
                    chunk = await r.read(8192)
                    if not chunk:
                        break
                    raw += chunk
            await asyncio.wait_for(_all(), 2.0)
            head, _, body = raw.partition(b"\r\n\r\n")
            if b" 200 " not in head.split(b"\r\n", 1)[0]:
                return None
            d = json.loads(body)
            return {**d, "url": f"http://{host}:{port}"} if isinstance(d, dict) and d.get("app") == "makemkv-web" else None
        except Exception:  # noqa: BLE001
            return None
        finally:
            if w:
                w.close()


async def run_scan(request_host: str = "", request_port: int = 0) -> None:
    if scan["running"]:
        return
    tg, nets = targets(request_host, request_port)
    scan.update(running=True, done=0, total=len(tg), found=[], started=time.time(), finished=0, nets=nets, error="", cancel=False)
    broadcast()
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(host: str, port: int):
        if scan["cancel"]:
            return
        d = await probe(host, port, sem)
        scan["done"] += 1
        if d:
            scan["found"].append({k: d.get(k) for k in ("id", "name", "version", "cores", "mem", "url", "pairing")})
            broadcast()
        elif scan["done"] % 32 == 0:
            broadcast()
    try:
        await asyncio.gather(*(one(h, p) for h, p in tg))
    except Exception as e:  # noqa: BLE001
        scan["error"] = str(e)
    scan.update(running=False, finished=time.time())
    broadcast()


def snapshot() -> dict:
    found = []
    for f in scan["found"]:
        n = store.by_remote_id(f["id"]) or store.by_url(f["url"])
        found.append({**f, "self": f["id"] == store.self_id(), "known": n["name"] if n else "", "paired": bool(n and n.get("token"))})
    return {"running": scan["running"], "done": scan["done"], "total": scan["total"], "found": found, "nets": scan["nets"],
            "started": scan["started"], "finished": scan["finished"], "error": scan["error"]}


@router.post("/scan")
async def api_scan(request: Request):
    if not store.active():
        raise HTTPException(409, "Im eigenständigen Betrieb gibt es keine Suche.")
    if not scan["running"]:
        host = (request.headers.get("host") or "").rsplit(":", 1)
        port = int(host[1]) if len(host) == 2 and host[1].isdigit() else 0
        asyncio.create_task(run_scan(host[0], port))
        await asyncio.sleep(0)
    return snapshot()


@router.post("/scan/cancel")
def api_scan_cancel():
    scan["cancel"] = True
    return snapshot()


@router.get("/scan")
def api_scan_state():
    return snapshot()


async def auto_search():
    """Optional (nodes.auto_search): alle 10 Minuten leise suchen; Funde werden nur angezeigt, nie automatisch verbunden."""
    await asyncio.sleep(30)
    while True:
        if store.active() and store.cfg()["auto_search"] and not scan["running"]:
            await run_scan()
        await asyncio.sleep(600)


ext.register_router(router)
ext.register_startup(auto_search)
