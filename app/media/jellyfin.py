"""Optional: Jellyfin nach dem Einsortieren zum Bibliotheks-Scan auffordern (POST /Library/Refresh)."""
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
    """Erreichbarkeit und Schlüssel prüfen (GET /System/Info). {ok, message}."""
    if not url or not key:
        return {"ok": False, "message": "Adresse und Schlüssel eintragen"}
    try:
        code, _ = await asyncio.to_thread(_call, url, key, "/System/Info", "GET")
    except (OSError, ValueError) as e:
        return {"ok": False, "message": f"Jellyfin nicht erreichbar: {e}"}
    if code in (401, 403):
        return {"ok": False, "message": "Jellyfin lehnt den Schlüssel ab"}
    return {"ok": code == 200, "message": "Verbindung ok" if code == 200 else f"Jellyfin antwortet mit {code}"}


async def refresh(url: str, key: str) -> dict:
    """Bibliotheks-Scan anstoßen. {ok, message} – ein Fehler stört das Einsortieren nie."""
    if not url or not key:
        return {"ok": False, "message": "nicht eingerichtet"}
    try:
        code, _ = await asyncio.to_thread(_call, url, key, "/Library/Refresh", "POST")
    except (OSError, ValueError) as e:
        return {"ok": False, "message": f"Jellyfin nicht erreichbar: {e}"}
    return {"ok": code in (200, 204), "message": "Bibliothek wird aktualisiert" if code in (200, 204) else f"Jellyfin antwortet mit {code}"}
