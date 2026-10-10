"""Zwischenspeicher und Übertragung ins Ausgabeziel."""
import asyncio
import json
import os
import shutil
import time
from pathlib import Path
import errno
from collections import deque
from app import cluster, convert, ext
from app.config import CONVERT, READY, STAGING, WORK, CONV_WORK
from app.files import out_dir, release_lock
from app.state import broadcast, drives, upload_queue, uploads
from app.util import fmt_bytes, mkdir_open, open_perms, tree_size, unique_path


def staging_free() -> int:
    STAGING.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(STAGING).free


_up_seq = 0


def enqueue_upload(src: Path, rel: str, dev: str = "", replace: bool = False, lock: str = "", orig_size: int = 0, then_convert: dict | None = None):
    global _up_seq
    _up_seq += 1
    item = {"id": _up_seq, "name": rel, "src": str(src), "size": tree_size(src), "copied": 0, "speed": 0.0, "eta": 0,
            "status": "queued", "error": "", "dev": dev, "t": time.time(), "replace": replace, "lock": lock, "orig_size": orig_size, "then_convert": then_convert}
    uploads.append(item)
    upload_queue.put_nowait(item)
    broadcast()


def copy_item(item: dict, base: Path, notify):
    """Kopiert eine fertige Datei (oder einen Ordner) ins Ziel: erst als .part, dann umbenennen, Größe prüfen, Quelle löschen."""
    src = Path(item["src"])
    target = base / item["name"]
    replace = bool(item.get("replace"))
    if replace:                                       # Bibliothek: konvertierte Datei ersetzt das Original (nur wenn es unverändert ist)
        if not target.is_file():
            raise OSError("Das Original ist nicht mehr vorhanden – Ergebnis bleibt im Zwischenspeicher")
        if item.get("orig_size") and target.stat().st_size != item["orig_size"]:
            raise OSError("Das Original wurde zwischenzeitlich verändert – es wird nicht ersetzt")
    mkdir_open(target.parent, base)
    if src.is_file():
        if not replace:
            target = unique_path(target)
        if os.stat(src).st_dev == os.stat(target.parent).st_dev:      # gleiches Dateisystem: nur umbenennen
            try:
                os.replace(src, target)
                open_perms(target, False)
                item.update(copied=item["size"], dest=str(target))
                return
            except OSError as e:
                if e.errno != errno.EXDEV:                              # zwei Einhängungen desselben Dateisystems: dann kopieren
                    raise
        files = [(src, target)]
    else:
        files = [(f, target / f.relative_to(src)) for f in sorted(src.rglob("*")) if f.is_file()]
    item["size"], item["copied"] = sum(a.stat().st_size for a, _ in files), 0
    last, t_start, win = 0.0, time.monotonic(), deque([(time.monotonic(), 0)], maxlen=8)
    for a, b in files:
        mkdir_open(b.parent, base)
        part = b.with_name(b.name + ".part")
        with open(a, "rb") as fi, open(part, "wb") as fo:
            while chunk := fi.read(8 * 2**20):
                fo.write(chunk)
                item["copied"] += len(chunk)
                if time.monotonic() - last > 0.5:
                    last = time.monotonic()
                    win.append((last, item["copied"]))          # gleitendes Fenster -> aktuelle Geschwindigkeit
                    dt = win[-1][0] - win[0][0]
                    if dt > 0:
                        item["speed"] = (win[-1][1] - win[0][1]) / dt
                        item["eta"] = (item["size"] - item["copied"]) / item["speed"] if item["speed"] > 0 else 0
                    notify()
            fo.flush()
            os.fsync(fo.fileno())
        if part.stat().st_size != a.stat().st_size:
            raise OSError(f"Größe von {b.name} stimmt nach dem Kopieren nicht")
        os.replace(part, b)
        open_perms(b, False)
    shutil.rmtree(src) if src.is_dir() else src.unlink()
    item["dest"] = str(target)
    try:
        if src.parent != READY:
            src.parent.rmdir()
    except OSError:
        pass


async def upload_worker():
    loop = asyncio.get_running_loop()

    def notify():
        loop.call_soon_threadsafe(broadcast)

    while True:
        item = await upload_queue.get()
        dr = drives.get(item["dev"])
        for attempt in range(1, 6):
            try:
                base, _ = await asyncio.to_thread(out_dir)
                item.update(status="copying", error="", copied=0)
                broadcast()
                await asyncio.to_thread(copy_item, item, base, notify)
                item.update(status="done", t=time.time(), speed=0.0, eta=0)
                if dr:
                    dr.add_log(f"Übertragen: {item['name']} ({fmt_bytes(item['size'])})", "ok")
                if item.get("lock"):
                    release_lock(item["lock"])
                if item.get("then_convert"):
                    await cluster.hand_to_peer_after_upload(item, base, dr)
                if ext.upload_hooks:
                    await ext.run_hooks(ext.upload_hooks, item)
                break
            except Exception as e:  # noqa: BLE001
                item.update(status="retry" if attempt < 5 else "error", error=str(e), speed=0.0, eta=0)
                if attempt == 5 and item.get("lock"):
                    release_lock(item["lock"])
                if dr:
                    dr.add_log(f"Übertragung von {item['name']} fehlgeschlagen: {e}", "error")
                broadcast()
                if attempt < 5:
                    await asyncio.sleep(30 * attempt)
        broadcast()


def recover_staging():
    """Beim Start: unfertige Arbeitsdateien verwerfen, fertige (noch nicht übertragene) erneut einreihen."""
    shutil.rmtree(WORK, ignore_errors=True)
    shutil.rmtree(CONV_WORK, ignore_errors=True)
    WORK.mkdir(parents=True, exist_ok=True)
    if CONVERT.exists():                      # fertig gerippt, Konvertierung war noch offen
        for folder in sorted(CONVERT.iterdir()):
            for f in sorted(folder.glob("*.mkv")) if folder.is_dir() else []:
                side = f.with_name(f.name + ".json")
                try:
                    cfg = convert.clean_convert(json.loads(side.read_text()))
                except (OSError, ValueError):
                    cfg = None
                if cfg and cfg["convert"]:
                    convert.enqueue_convert(f, folder.name, cfg)
                else:
                    convert.release_original({"src": str(f), "folder": folder.name, "dev": ""})
    READY.mkdir(parents=True, exist_ok=True)
    for folder in sorted(READY.iterdir()):
        if folder.is_dir():
            entries = list(folder.iterdir())
            for e in entries:
                if not e.name.endswith(".part"):
                    enqueue_upload(e, f"{folder.name}/{e.name}")
            if not entries:
                folder.rmdir()
