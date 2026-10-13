"""Optional password protection (HTTP Basic) with two exceptions for the machine cluster (package C):

- Paired machines identify themselves with the pairing token (header `X-Node-Token`) and get through even when a
  password is set. Whoever checks the token registers via `register_token_checker` (app/nodes.py).
- A few paths must be reachable without login before pairing (discovery, pairing request): `allow_public`.
"""
import base64
import re
import secrets
from typing import Callable

from fastapi import Request, Response
from app.config import AUTH_PASS, AUTH_USER

token_checkers: list[Callable[[str], bool]] = []
public_paths: list[re.Pattern] = []


def register_token_checker(fn: Callable[[str], bool]) -> None:
    """`fn(token) -> bool`: does the token belong to a paired machine?"""
    token_checkers.append(fn)


def allow_public(pattern: str) -> None:
    """Path (complete, with /api/) is reachable without a password too."""
    public_paths.append(re.compile(pattern))


def token_valid(request: Request) -> bool:
    tok = request.headers.get("x-node-token", "")
    return bool(tok) and any(chk(tok) for chk in token_checkers)


async def basic_auth(request: Request, call_next):
    if AUTH_PASS:
        ok = token_valid(request) or any(p.fullmatch(request.url.path) for p in public_paths)
        h = request.headers.get("authorization", "")
        if not ok and h.startswith("Basic "):
            try:
                u, _, p = base64.b64decode(h[6:]).decode().partition(":")
                ok = secrets.compare_digest(u.encode(), AUTH_USER.encode()) and secrets.compare_digest(p.encode(), AUTH_PASS.encode())
            except Exception:  # noqa: BLE001
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Spindle"'})
    return await call_next(request)
