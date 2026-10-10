"""Einsortieren ausführen (im Hintergrund, mit Fortschritt), Verlauf führen und die letzte Aktion rückgängig machen."""
import asyncio
import time
import uuid
from pathlib import Path

from app import files, state
from app.media import conf, jellyfin, moves, plan as planner, series, store

ops: dict[str, dict] = {}            # laufende und kürzlich beendete Aktionen (nur im Arbeitsspeicher)
HISTORY_MAX = 50


def key_for(p: Path) -> str:
    """Schlüssel für Begleitdaten: relativ zum Ausgabeordner, sonst absolut."""
    try:
        return str(p.resolve().relative_to(files.out_dir()[0].resolve()))
    except ValueError:
        return str(p)


def history() -> list:
    return store.load("history.json", [])


def last_undoable() -> dict | None:
    h = history()
    return h[-1] if h and not h[-1].get("undone") and h[-1].get("rows") else None


async def start(req: dict) -> dict:
    """Plan neu berechnen (dem Browser wird nicht vertraut) und die Ausführung starten. Rückgabe: {id, plan}."""
    p = planner.build_plan(req)
    if not p["ok"] and not p["summary"]["move"]:
        raise planner.PlanError("Nichts zu tun: keine Datei kann einsortiert werden.")
    if p["summary"]["error"]:
        raise planner.PlanError("Der Plan enthält Fehler, bitte die Vorschau prüfen.")
    if any(o["status"] == "running" for o in ops.values()):
        raise planner.PlanError("Es läuft schon eine Einsortier-Aktion.")
    oid = uuid.uuid4().hex[:8]
    ops[oid] = {"id": oid, "status": "running", "t": time.time(), "title": req.get("title") or "", "rows": [{**r} for r in p["rows"]], "copied": 0,
                "total": p["summary"]["bytes"], "jellyfin": None, "history_id": None}
    asyncio.create_task(_run(oid, req, p))
    return {"id": oid, "plan": p}


async def _run(oid: str, req: dict, p: dict):
    op, st = ops[oid], conf.cfg()
    root, done_rows, created = Path(p["root"]), [], []
    base_copied = 0
    first_src_dirs: set[Path] = set()
    try:
        for row in op["rows"]:
            if row["status"] != "move":
                continue
            src, dst = files.inside_out(row["src"]), root / row["dst"]
            try:
                if not src.is_file():
                    raise OSError("Datei nicht mehr vorhanden")
                why = files.busy_reason(row["src"], False, src)
                if why:
                    raise OSError(why)
                owner = files.acquire_lock(src)
                if owner:
                    raise OSError(f"wird gerade von „{owner}“ bearbeitet")
                lp = str(files.lock_path(src))
                try:
                    created += await asyncio.to_thread(moves.make_dirs, dst.parent, root)
                    row["status"] = "working"
                    size = src.stat().st_size

                    def progress(n, b=base_copied):
                        op["copied"] = b + n
                    how = await asyncio.to_thread(moves.move_file, src, dst, st["action"], progress)
                finally:
                    files.release_lock(lp)
                base_copied += size
                op["copied"] = base_copied
                row.update(status="done", how=how)
                done_rows.append({"src": str(src), "src_rel": row["src"], "dst": str(dst), "size": size, "how": how, "role": row["role"]})
                first_src_dirs.add(src.parent)
            except (OSError, FileExistsError) as e:
                row.update(status="error", why=str(e))
            state.broadcast()
        removed = []
        if st["action"] == "verschieben":
            out_base = files.out_dir()[0]
            for d in sorted(first_src_dirs, key=lambda x: -len(x.parts)):
                removed += moves.prune_empty(d, out_base)
        prev = _remember(req, op, done_rows, p)
        entry = {"id": oid, "t": time.time(), "title": req.get("title") or "", "kind": req["kind"], "action": st["action"], "rows": done_rows,
                 "created_dirs": [str(d) for d in created], "removed_dirs": [str(d) for d in removed], "undone": False, "progress": prev}
        if done_rows:
            h = history()
            h.append(entry)
            del h[:-HISTORY_MAX]
            store.save("history.json")
            op["history_id"] = oid
            if st["jellyfin_scan"]:
                op["jellyfin"] = await jellyfin.refresh(st["jellyfin_url"], st["jellyfin_key"])
        op["status"] = "done" if done_rows else "failed"
    except Exception as e:  # noqa: BLE001
        op.update(status="failed", error=str(e))
    state.broadcast()


def _remember(req: dict, op: dict, done_rows: list, p: dict) -> dict | None:
    """Medien-Einträge je Ziel-Datei speichern (für `info`), Begleitdaten umhängen, Serienfortschritt merken."""
    items = {it["path"]: it for it in req.get("items") or []}
    data = store.load("items.json", {})
    prev = None
    eps = []
    for r in done_rows:
        it = items.get(r["src_rel"], {})
        k = key_for(Path(r["dst"]))
        data[k] = {"kind": req["kind"], "title": req.get("title"), "year": req.get("year"), "tmdb": req.get("tmdb"), "imdb": req.get("imdb"),
                   "poster": req.get("poster"), "role": it.get("role"), "season": it.get("season"),
                   "episodes": it.get("episodes"), "name": it.get("name"), "t": time.time()}
        if r["how"] != "copy-keep":
            store.move_keys(r["src_rel"], k)
        if req["kind"] == "series" and it.get("role") == "episode" and it.get("episodes"):
            eps += list(it["episodes"])
    store.save("items.json")
    if req["kind"] == "series" and eps and req.get("season") is not None:
        k = series.key(req.get("title"), req.get("year"), req.get("tmdb"))
        prev = {"key": k, "season": int(req["season"]), "old": series.remember(k, int(req["season"]), req.get("disc"), min(eps), max(eps))}
    return prev


def undo(oid: str) -> dict:
    """Nur die jeweils letzte, noch nicht zurückgenommene Aktion. Dateien gehen an ihren alten Ort; bei „kopieren“ wird die Kopie entfernt."""
    entry = last_undoable()
    if not entry or entry["id"] != oid:
        raise planner.PlanError("Nur die letzte Aktion lässt sich rückgängig machen.")
    results = []
    for r in reversed(entry["rows"]):
        src, dst = Path(r["src"]), Path(r["dst"])
        try:
            if not dst.is_file() or dst.stat().st_size != r["size"]:
                raise OSError("Datei im Ziel nicht mehr vorhanden oder verändert")
            if r["how"] == "copy-keep":
                store.load("items.json", {}).pop(key_for(dst), None)
                dst.unlink()
            else:
                if src.exists():
                    raise OSError("am alten Ort liegt schon etwas")
                moves.make_dirs(src.parent, files.out_dir()[0])
                store.load("items.json", {}).pop(key_for(dst), None)
                moves.move_file(dst, src, "verschieben")
                store.move_keys(key_for(dst), r["src_rel"])
            results.append({"dst": str(dst), "ok": True})
        except (OSError, FileExistsError) as e:
            results.append({"dst": str(dst), "ok": False, "why": str(e)})
    store.save("items.json")
    for d in sorted(entry["created_dirs"], key=lambda x: -len(Path(x).parts)):
        try:
            Path(d).rmdir()
        except OSError:
            pass
    prog = entry.get("progress")
    if prog:
        series.restore(prog["key"], prog["season"], prog["old"])
    failed = {x["dst"] for x in results if not x["ok"]}
    if failed:                                    # Rest bleibt rückgängig-fähig
        entry["rows"] = [r for r in entry["rows"] if r["dst"] in failed]
    else:
        entry["undone"] = True
    store.save("history.json")
    state.broadcast()
    return {"ok": all(x["ok"] for x in results), "results": results}
