"""Optional: ask Jellyfin to scan its library after sorting (POST /Library/Refresh)."""
import asyncio
import urllib.error
import urllib.request


def _call(url: str, key: str, path: str, method: str) -> tuple[int, str]:
    req = urllib.request.Request(url.rstrip("/") + path, method=method, headers={"Authorization": f'MediaBrowser Token="{key}"', "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, r.read(2000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        with e:
            return e.code, ""


async def test(url: str, key: str) -> dict:
    """Check reachability and the key (GET /System/Info). {ok, message}."""
    if not url or not key:
        return {"ok": False, "message": "Enter the address and the key"}
    try:
        code, _ = await asyncio.to_thread(_call, url, key, "/System/Info", "GET")
    except (OSError, ValueError) as e:
        return {"ok": False, "message": f"Jellyfin not reachable: {e}"}
    if code in (401, 403):
        return {"ok": False, "message": "Jellyfin refuses the key"}
    return {"ok": code == 200, "message": "Connection ok" if code == 200 else f"Jellyfin answers with {code}"}


async def refresh(url: str, key: str) -> dict:
    """Trigger a library scan. {ok, message} – an error never disturbs the sorting."""
    if not url or not key:
        return {"ok": False, "message": "not set up"}
    try:
        code, _ = await asyncio.to_thread(_call, url, key, "/Library/Refresh", "POST")
    except (OSError, ValueError) as e:
        return {"ok": False, "message": f"Jellyfin not reachable: {e}"}
    return {"ok": code in (200, 204), "message": "Library is being refreshed" if code in (200, 204) else f"Jellyfin answers with {code}"}
