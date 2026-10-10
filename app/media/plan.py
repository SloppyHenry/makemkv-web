"""Einsortieren planen (ohne etwas zu ändern): Zielpfade nach Jellyfin-Schema, Konflikte, gesperrte Dateien, neue Ordner.

Eingabe (`req`): {kind: movie|series, title, year, tmdb, imdb, items: [{path, role: movie|episode|extra|skip, season, episodes, name, version,
extra_kind}], decisions: {pfad: "skip"|"rename"}}; Pfade relativ zum Ausgabeordner.
Ausgabe: {ok, root, action, naming, same_fs, rows, dirs, summary}; `rows[i].status`: move | conflict | locked | skip | missing | error.
"""
import time
from pathlib import Path

from fastapi import HTTPException

from app import files
from app.media import conf, naming
from app.media.moves import same_device
from app.util import fmt_bytes, safe_name

VIDEO = naming.VIDEO_EXT


class PlanError(Exception):
    pass


def target_root(kind: str, st: dict) -> Path:
    d = st["movies_dir"] if kind == "movie" else st["series_dir"]
    if not d:
        raise PlanError("Der Ordner für " + ("Filme" if kind == "movie" else "Serien") + " ist noch nicht eingestellt (Einstellungen → Medien / Jellyfin).")
    try:
        return conf.inside_root(d)
    except HTTPException as e:
        raise PlanError(f"{d}: {e.detail}")


def dest_rel(req: dict, it: dict, st: dict) -> str:
    """Zielpfad einer Datei relativ zum Filme-/Serien-Ordner."""
    if st["naming"] == "unveraendert":
        return it["path"]
    p = Path(it["path"])
    ext = p.suffix.lower() if p.suffix.lower() in VIDEO else p.suffix
    stem = p.stem
    common = dict(imdb=req.get("imdb"), tmdb=req.get("tmdb"), tags=st["id_tags"])
    title, year = req.get("title") or "", req.get("year")
    if req["kind"] == "movie":
        if it["role"] == "extra":
            return naming.movie_rel(title, year, ext, extra=it.get("extra_kind") or "extras", extra_name=it.get("name") or stem, **common)
        return naming.movie_rel(title, year, ext, version=it.get("version") or "", **common)
    if it["role"] == "extra":
        return naming.series_extra_rel(title, year, int(it.get("season") or 1), ext, extra=it.get("extra_kind") or "extras", extra_name=it.get("name") or stem, **common)
    try:
        return naming.episode_rel(title, year, int(it.get("season") if it.get("season") is not None else 1), list(it.get("episodes") or []), ext,
                                  ep_name=(it.get("name") or "") if st["episode_names"] else "", **common)
    except ValueError as e:
        raise PlanError(f"{p.name}: {e}")


def build_plan(req: dict) -> dict:
    st = conf.cfg()
    if req.get("kind") not in ("movie", "series"):
        raise PlanError("Art fehlt (Film oder Serie).")
    if st["naming"] == "jellyfin" and not (req.get("title") or "").strip():
        raise PlanError("Titel fehlt.")
    root = target_root(req["kind"], st)
    decisions = req.get("decisions") or {}
    rows, taken = [], set()
    for it in req.get("items") or []:
        rel = it["path"]
        row = {"src": rel, "role": it.get("role", ""), "dst": "", "status": "move", "why": "", "size": 0}
        rows.append(row)
        if it.get("role") == "skip":
            row.update(status="skip", why=it.get("why") or "ausgelassen")
            continue
        try:
            src = files.inside_out(rel)
        except HTTPException:
            row.update(status="error", why="ungültiger Pfad")
            continue
        if not src.is_file():
            row.update(status="missing", why="Datei nicht mehr vorhanden")
            continue
        row["size"] = src.stat().st_size
        why = files.busy_reason(rel, False, src)
        if not why and files.fresh_lock_in(src, False):
            why = "wird gerade von einer anderen Instanz bearbeitet"
        if why:
            row.update(status="locked", why=why[0].upper() + why[1:])
        try:
            row["dst"] = dest_rel(req, it, st)
        except PlanError as e:
            row.update(status="error", why=str(e))
            continue
        dst = root / row["dst"]
        if root not in dst.resolve().parents:
            row.update(status="error", why="Zielpfad außerhalb des Ziels")
            continue
        if dst == src:
            row.update(status="skip", why="liegt schon dort", dst=row["dst"])
            continue
        if dst.exists() or str(dst) in taken:
            if decisions.get(rel) == "rename":
                n = 2
                while (root / naming.unique_variant(row["dst"], n)).exists() or str(root / naming.unique_variant(row["dst"], n)) in taken:
                    n += 1
                row["dst"] = naming.unique_variant(row["dst"], n)
                dst = root / row["dst"]
                row["why"] = "Ziel existierte schon, anderer Name"
            else:
                try:
                    old = dst.stat()
                    info = f" ({fmt_bytes(old.st_size)}, {time.strftime('%d.%m.%Y', time.localtime(old.st_mtime))})"
                except OSError:
                    info = ""
                row.update(status="conflict" if row["status"] == "move" else row["status"], why="Existiert schon im Ziel" + info if dst.exists() else "Zwei Dateien hätten denselben Namen")
                continue
        if row["status"] == "move":
            taken.add(str(dst))
    dirs, seen = [], set()
    for row in rows:
        if row["status"] in ("move", "locked", "conflict") and row["dst"]:
            parts = Path(row["dst"]).parent.parts
            for i in range(1, len(parts) + 1):
                d = "/".join(parts[:i])
                if d not in seen:
                    seen.add(d)
                    dirs.append({"rel": d, "exists": (root / d).is_dir()})
    first = next((r for r in rows if r["status"] == "move"), None)
    same_fs = bool(first and same_device(files.inside_out(first["src"]), root / first["dst"]))
    count = {k: sum(1 for r in rows if r["status"] == k) for k in ("move", "conflict", "locked", "skip", "missing", "error")}
    return {"ok": count["move"] > 0 and not count["error"], "root": str(root), "action": st["action"], "naming": st["naming"], "same_fs": same_fs,
            "rows": rows, "dirs": dirs, "summary": {**count, "bytes": sum(r["size"] for r in rows if r["status"] == "move")},
            "new_dirs": [d["rel"] for d in dirs if not d["exists"]], "free": conf.check_dir(str(root)).get("free", 0),
            "name": safe_name(req.get("title") or "")}

