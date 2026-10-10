"""Optionaler Passwortschutz (HTTP Basic)."""
import base64
import secrets

from fastapi import Request, Response
from app.config import AUTH_PASS, AUTH_USER


async def basic_auth(request: Request, call_next):
    if AUTH_PASS:
        ok = False
        h = request.headers.get("authorization", "")
        if h.startswith("Basic "):
            try:
                u, _, p = base64.b64decode(h[6:]).decode().partition(":")
                ok = secrets.compare_digest(u.encode(), AUTH_USER.encode()) and secrets.compare_digest(p.encode(), AUTH_PASS.encode())
            except Exception:  # noqa: BLE001
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="MakeMKV-Web"'})
    return await call_next(request)
