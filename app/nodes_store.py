"""Rechnerliste (DATA/nodes.json), eigene Identität und Einstellungen des Namensraums `nodes`.

Ein Eintrag der Liste:
  nid      lokale Kennung des Eintrags (uuid), für die REST-Pfade
  name     Anzeigename (Alias) – zugleich der Schlüssel in `peers` und in `/api/peer/{name}/…`
  url      Adresse, z. B. http://192.168.178.7:8780
  id       Instanz-ID des anderen Rechners (leer bei alten Rechnern)
  token    gemeinsames Kopplungs-Token (leer = nicht gekoppelt)
  trust    "paired" (Token) | "legacy" (ohne Token, wie bisher vertraut)
  origin   "peers" (Umgebungsvariable) | "manual" | "pairing" | "discovery"
Die Tokens verlassen diese Datei nie (nicht in Einstellungen, nicht in /api/state).
"""
import ipaddress
import json
import os
import re
import secrets
import time
import uuid
from urllib.parse import urlsplit

from app import state
from app.config import DATA, INSTANCE

FILE = DATA / "nodes.json"
DEFAULT_PORT = 8780
DEFAULTS = {"mode": "standalone", "discoverable": False, "name": "", "public_url": "", "scan_nets": "", "auto_search": False}
STARTED = time.time()

data: dict = {"v": 1, "id": "", "nodes": [], "env_seen": []}
loaded = False


def cfg() -> dict:
    return {**DEFAULTS, **(state.settings.get("nodes") or {})}


def active() -> bool:
    """Verbund-Betrieb? (Eigenständig: keine Abfragen, keine Suche, nicht auffindbar.)"""
    return cfg()["mode"] == "verbund"


def self_name() -> str:
    return cfg()["name"].strip() or INSTANCE


def self_id() -> str:
    return data["id"]


# ---------- Datei
def load() -> bool:
    """Liest nodes.json. Gibt False zurück, wenn die Datei neu angelegt werden muss (erster Start mit diesem Stand)."""
    global loaded
    fresh = True
    try:
        d = json.loads(FILE.read_text())
        if isinstance(d, dict) and isinstance(d.get("nodes"), list):
            data.update({"v": 1, "id": d.get("id") or "", "nodes": [n for n in d["nodes"] if isinstance(n, dict) and n.get("url")],
                         "env_seen": d.get("env_seen") if isinstance(d.get("env_seen"), list) else []})
            fresh = False
    except (OSError, ValueError):
        pass
    if not data["id"]:
        data["id"] = uuid.uuid4().hex
    for n in data["nodes"]:
        n.setdefault("nid", uuid.uuid4().hex)
        n.setdefault("id", "")
        n.setdefault("token", "")
        n.setdefault("trust", "paired" if n.get("token") else "legacy")
        n.setdefault("origin", "manual")
        n.setdefault("added", time.time())
    loaded = True
    return not fresh


def save() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, FILE)


# ---------- Namen und Adressen
NAME_BAD = re.compile(r'[/\\?#%,\x00-\x1f]')


def clean_name(raw: str) -> str:
    """Alias: kein Pfad-/URL-Zeichen (er steht in /api/peer/<name>/…), höchstens 40 Zeichen. Leer = ungültig."""
    return NAME_BAD.sub("", (raw or "")).strip(" .")[:40]


def unique_name(raw: str, fallback: str = "rechner", skip_nid: str = "") -> str:
    base = clean_name(raw) or fallback
    taken = {n["name"].lower() for n in data["nodes"] if n["nid"] != skip_nid} | {INSTANCE.lower(), self_name().lower()}
    name, i = base, 2
    while name.lower() in taken:
        name, i = f"{base[:36]}-{i}", i + 1
    return name


def norm_url(raw: str) -> str:
    """„192.168.178.7“, „host:8781“ oder „http://host:8780/“ -> „http://host:8780“; leer, wenn unbrauchbar."""
    s = (raw or "").strip()
    if not s:
        return ""
    if "://" not in s:
        s = "http://" + s
    try:
        u = urlsplit(s)
        host, port = u.hostname, u.port
    except ValueError:
        return ""
    if u.scheme not in ("http", "https") or not host or not re.fullmatch(r"[A-Za-z0-9.\-]+|[0-9A-Fa-f:]+", host):
        return ""
    if ":" in host:
        host = f"[{host}]"
    return f"{u.scheme}://{host}:{port or DEFAULT_PORT}"


def url_host(url: str) -> str:
    return urlsplit(url).hostname or ""


def is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback or host in ("localhost",)
    except ValueError:
        return host.lower() == "localhost"


# ---------- Zugriff
def nodes() -> list[dict]:
    return data["nodes"]


def by_nid(nid: str):
    return next((n for n in data["nodes"] if n["nid"] == nid), None)


def by_name(name: str):
    return next((n for n in data["nodes"] if n["name"] == name), None)


def by_url(url: str):
    u = norm_url(url)
    return next((n for n in data["nodes"] if n["url"] == u), None)


def by_remote_id(rid: str):
    return next((n for n in data["nodes"] if rid and n.get("id") == rid), None)


def add(name: str, url: str, origin: str, remote_id: str = "", token: str = "") -> dict:
    n = {"nid": uuid.uuid4().hex, "name": unique_name(name), "url": url, "id": remote_id, "token": token,
         "trust": "paired" if token else "legacy", "origin": origin, "added": time.time()}
    data["nodes"].append(n)
    save()
    return n


def remove(n: dict) -> None:
    data["nodes"] = [x for x in data["nodes"] if x["nid"] != n["nid"]]
    state.peers_state.pop(n["name"], None)
    save()


def public(n: dict) -> dict:
    """Eintrag ohne Token (für Oberfläche und /api/state)."""
    return {k: v for k, v in n.items() if k != "token"} | {"paired": bool(n.get("token"))}


# ---------- Token
def new_token() -> str:
    return secrets.token_urlsafe(32)


def node_for_token(token: str):
    for n in data["nodes"]:
        if n.get("token") and secrets.compare_digest(n["token"].encode(), token.encode()):
            return n
    return None


def token_ok(token: str) -> bool:
    return node_for_token(token) is not None


def token_for_url(url: str) -> str:
    n = by_url(url)
    return n["token"] if n else ""


def mem_total() -> int:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return 0
