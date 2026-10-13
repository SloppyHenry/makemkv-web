"""Extension points: modules register here without changing core modules.

This module imports nothing from `app`, so that any other module can load it safely.
Description and examples: docs/agents/schnittstellen.md
"""
import asyncio
import inspect
import re
import traceback
from typing import Any, Callable

routers: list = []                              # APIRouters that main.py includes
settings_ns: dict[str, dict] = {}               # namespace -> {"model", "defaults", "secret", "on_change"}
snapshot_fns: dict[str, Callable[[], Any]] = {}  # key -> function whose result ends up in /api/state
capabilities: dict[str, Any] = {}               # capabilities of this machine (/api/state -> capabilities)
startup_fns: list[Callable] = []                # async functions that run as background tasks on startup
rip_hooks: list[Callable] = []                  # after every finished ripped title
scan_hooks: list[Callable] = []                 # after every analysis of a disc
auto_scan_checks: list[Callable[[], bool]] = []  # True = analyze the disc on insertion even if "analyze automatically" is off
upload_hooks: list[Callable] = []               # after every finished transferred file
proxy_allowed: list[re.Pattern] = []            # paths that /api/peer/{name}/… may forward


def register_router(router) -> None:
    """Include your own `APIRouter` (prefix e.g. /api/player) in the app."""
    if router not in routers:
        routers.append(router)


def register_settings(namespace: str, model, defaults: dict, secret: tuple = (), on_change: Callable | None = None) -> None:
    """Register a settings namespace. `model` is a pydantic model, `defaults` the defaults.
    Fields in `secret` are not output in /api/state and GET /api/settings (only `<field>_set: true`)."""
    settings_ns[namespace] = {"model": model, "defaults": defaults, "secret": tuple(secret), "on_change": on_change}


def register_snapshot(key: str, fn: Callable[[], Any]) -> None:
    """`fn()` (JSON-serializable, fast, without network access) is included in every state report under `key`."""
    snapshot_fns[key] = fn


def register_capability(name: str, value: Any) -> None:
    """Report a capability of this machine, e.g. ('encoders', ['libx265', 'libx264']). Other machines see it in the cluster."""
    capabilities[name] = value


def register_startup(fn: Callable) -> None:
    """`async def fn()` is started as a background task on startup (after the settings are loaded)."""
    startup_fns.append(fn)


def register_rip_hook(fn: Callable) -> None:
    """`fn(info: dict)` (sync or async) is called after every finished ripped title.
    info: dev, disc (name, type, volume, all titles), title (id, name, duration, bytes, chapters …), rel (target path in the output folder),
    folder, mode, converting (bool). Errors in the hook are logged and do not disturb the rip."""
    rip_hooks.append(fn)


def register_scan_hook(fn: Callable, force_auto_scan: Callable[[], bool] | None = None) -> None:
    """`fn(info: dict)` (sync or async) after every analysis of a disc (also failed ones): info: drive (drive object), auto (bool,
    started by the poller on insertion). `force_auto_scan()` -> True: inserted discs are analyzed even with `auto_scan` switched off."""
    scan_hooks.append(fn)
    if force_auto_scan:
        auto_scan_checks.append(force_auto_scan)


def auto_scan_forced() -> bool:
    for fn in auto_scan_checks:
        try:
            if fn():
                return True
        except Exception:  # noqa: BLE001
            print(f"auto_scan check {getattr(fn, '__name__', fn)} failed:\n{traceback.format_exc()}", flush=True)
    return False


def register_upload_hook(fn: Callable) -> None:
    """`fn(item: dict)` (sync or async) after every file transferred to the target: item['name'] (requested path), item['dest'] (actual path)."""
    upload_hooks.append(fn)


def allow_proxy(pattern: str | re.Pattern) -> None:
    """Allows `POST /api/peer/{name}/<path>` to forward calls whose path (without /api/) fully matches `pattern`."""
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
            print(f"Hook {getattr(fn, '__name__', fn)} failed:\n{traceback.format_exc()}", flush=True)


def start_all() -> None:
    for fn in startup_fns:
        asyncio.create_task(fn())
