"""Machine list (DATA/nodes.json), own identity and the settings of the `nodes` namespace.

An entry of the list:
  nid      local id of the entry (uuid), for the REST paths
  name     display name (alias) – also the key in `peers` and in `/api/peer/{name}/…`
  url      address, e.g. http://192.168.178.7:8780
  id       instance id of the other machine (empty for old machines)
  token    shared pairing token (empty = not paired)
  trust    "paired" (token) | "legacy" (without token, trusted as before)
  origin   "peers" (environment variable) | "manual" | "pairing" | "discovery"
The tokens never leave this file (not in the settings, not in /api/state).
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
DEFAULTS = {"mode": "verbund", "pairing_required": False, "name": "", "public_url": "", "scan_nets": "", "auto_search": False}
STARTED = time.time()

data: dict = {"v": 1, "id": "", "nodes": [], "env_seen": []}
loaded = False


def cfg() -> dict:
    return {**DEFAULTS, **(state.settings.get("nodes") or {})}


def active() -> bool:
    """Cluster mode? (Standalone: no polling, no search, not discoverable. In cluster mode every machine is always discoverable.)"""
    return cfg()["mode"] == "verbund"


def self_name() -> str:
    return cfg()["name"].strip() or INSTANCE


def self_id() -> str:
    return data["id"]


# ---------- file
def load() -> bool:
    """Reads nodes.json. Returns False if the file has to be created (first start with this version)."""
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


# ---------- names and addresses
NAME_BAD = re.compile(r'[/\\?#%,\x00-\x1f]')


def clean_name(raw: str) -> str:
    """Alias: no path/URL characters (it appears in /api/peer/<name>/…), at most 40 characters. Empty = invalid."""
    return NAME_BAD.sub("", (raw or "")).strip(" .")[:40]


def unique_name(raw: str, fallback: str = "machine", skip_nid: str = "") -> str:
    base = clean_name(raw) or fallback
    taken = {n["name"].lower() for n in data["nodes"] if n["nid"] != skip_nid} | {INSTANCE.lower(), self_name().lower()}
    name, i = base, 2
    while name.lower() in taken:
        name, i = f"{base[:36]}-{i}", i + 1
    return name


def norm_url(raw: str) -> str:
    """Turns "192.168.178.7", "host:8781" or "http://host:8780/" -> "http://host:8780"; empty if unusable."""
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


# ---------- access
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
    """Entry without token (for the interface and /api/state)."""
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
