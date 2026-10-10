"""Auslieferung der Oberfläche: Gerüst (index.html) mit automatisch eingetragenen Stylesheets und Modulen."""
import json
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

STATIC = Path(__file__).parent / "static"
router = APIRouter()

# Reihenfolge, in der sich die Kernmodule anmelden (bestimmt die Reihenfolge der onState-Aufrufe); alle weiteren folgen alphabetisch
JS_ORDER = ["drives", "titles", "files", "logs", "jobs", "handover", "library", "settings", "nav"]
CSS_ORDER = ["base", "layout", "components", "shell", "jobs", "library"]
NOT_MODULES = {"core", "registry", "app"}      # werden von den Modulen importiert bzw. von index.html geladen


class NoCacheStatic(StaticFiles):
    """Browser prüfen bei jedem Laden per ETag nach – so mischt nach einem Update niemand alte und neue Module."""

    async def get_response(self, path, scope):
        r = await super().get_response(path, scope)
        r.headers["Cache-Control"] = "no-cache"
        return r


def _ordered(names: list[str], order: list[str]) -> list[str]:
    return [n for n in order if n in names] + sorted(n for n in names if n not in order)


def css_files() -> list[str]:
    return _ordered([p.stem for p in (STATIC / "css").glob("*.css")], CSS_ORDER)


def js_modules() -> list[str]:
    return _ordered([p.stem for p in (STATIC / "js").glob("*.js") if p.stem not in NOT_MODULES], JS_ORDER)


def assets_html() -> str:
    links = "".join(f'<link rel="stylesheet" href="/static/css/{n}.css">\n' for n in css_files())
    mods = json.dumps([f"/static/js/{n}.js" for n in js_modules()])
    return f"{links}<script>window.UI_MODULES = {mods};</script>"


@router.get("/", response_class=HTMLResponse)
def index():
    html = (STATIC / "index.html").read_text(encoding="utf-8").replace("<!--ASSETS-->", assets_html())
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})
