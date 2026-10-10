"""Erweiterungspunkte: Hier melden sich Module an, ohne Kernmodule zu ändern.

Dieses Modul importiert nichts aus `app`, damit jedes andere Modul es gefahrlos laden kann.
Beschreibung und Beispiele: docs/agenten/schnittstellen.md
"""
import asyncio
import inspect
import re
import traceback
from typing import Any, Callable

routers: list = []                              # APIRouter, die main.py einbindet
settings_ns: dict[str, dict] = {}               # Namensraum -> {"model", "defaults", "secret", "on_change"}
snapshot_fns: dict[str, Callable[[], Any]] = {}  # Schlüssel -> Funktion, deren Ergebnis in /api/state landet
capabilities: dict[str, Any] = {}               # Fähigkeiten dieses Rechners (/api/state -> capabilities)
startup_fns: list[Callable] = []                # async-Funktionen, die beim Start als Hintergrundaufgabe laufen
rip_hooks: list[Callable] = []                  # nach jedem fertig gerippten Titel
upload_hooks: list[Callable] = []               # nach jeder fertig übertragenen Datei
proxy_allowed: list[re.Pattern] = []            # Pfade, die /api/peer/{name}/… weiterleiten darf


def register_router(router) -> None:
    """Eigenen `APIRouter` (Präfix z. B. /api/player) in die App einbinden."""
    if router not in routers:
        routers.append(router)


def register_settings(namespace: str, model, defaults: dict, secret: tuple = (), on_change: Callable | None = None) -> None:
    """Einstellungs-Namensraum anmelden. `model` ist ein pydantic-Modell, `defaults` die Vorgaben.
    Felder in `secret` werden in /api/state und GET /api/settings nicht ausgegeben (nur `<feld>_set: true`)."""
    settings_ns[namespace] = {"model": model, "defaults": defaults, "secret": tuple(secret), "on_change": on_change}


def register_snapshot(key: str, fn: Callable[[], Any]) -> None:
    """`fn()` (JSON-fähig, schnell, ohne Netzwerkzugriffe) wird in jede Statusmeldung unter `key` aufgenommen."""
    snapshot_fns[key] = fn


def register_capability(name: str, value: Any) -> None:
    """Fähigkeit dieses Rechners melden, z. B. ('encoders', ['libx265', 'libx264']). Andere Rechner sehen sie im Verbund."""
    capabilities[name] = value


def register_startup(fn: Callable) -> None:
    """`async def fn()` wird beim Start als Hintergrundaufgabe gestartet (nach dem Laden der Einstellungen)."""
    startup_fns.append(fn)


def register_rip_hook(fn: Callable) -> None:
    """`fn(info: dict)` (sync oder async) wird nach jedem fertig gerippten Titel aufgerufen.
    info: dev, disc (Name, Typ, Volume, alle Titel), title (id, name, duration, bytes, chapters …), rel (Zielpfad im Ausgabeordner),
    folder, mode, converting (bool). Fehler im Hook werden protokolliert und stören den Rip nicht."""
    rip_hooks.append(fn)


def register_upload_hook(fn: Callable) -> None:
    """`fn(item: dict)` (sync oder async) nach jeder ins Ziel übertragenen Datei: item['name'] (angefragter Pfad), item['dest'] (echter Pfad)."""
    upload_hooks.append(fn)


def allow_proxy(pattern: str | re.Pattern) -> None:
    """Erlaubt, dass `POST /api/peer/{name}/<pfad>` Aufrufe weiterleitet, deren Pfad (ohne /api/) vollständig auf `pattern` passt."""
    proxy_allowed.append(re.compile(pattern) if isinstance(pattern, str) else pattern)


def proxy_ok(path: str) -> bool:
    return any(r.fullmatch(path) for r in proxy_allowed)


async def run_hooks(hooks: list[Callable], arg) -> None:
    for fn in list(hooks):
        try:
            r = fn(arg)
            if inspect.isawaitable(r):
                await r
        except Exception:  # noqa: BLE001
            print(f"Hook {getattr(fn, '__name__', fn)} fehlgeschlagen:\n{traceback.format_exc()}", flush=True)


def start_all() -> None:
    for fn in startup_fns:
        asyncio.create_task(fn())
