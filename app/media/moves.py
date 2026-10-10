"""Dateien sicher verschieben oder kopieren: nie überschreiben, kopieren mit Größenprüfung, leere Ordner aufräumen."""
import os
from pathlib import Path
from typing import Callable

from app.util import open_perms

CHUNK = 8 * 1024 * 1024


def nearest_existing(p: Path) -> Path:
    while not p.exists() and p != p.parent:
        p = p.parent
    return p


def same_device(src: Path, dst: Path) -> bool:
    """Liegen Quelle und (künftiges) Ziel auf demselben Dateisystem? Dann genügt Umbenennen."""
    try:
        return src.stat().st_dev == nearest_existing(dst.parent).stat().st_dev
    except OSError:
        return False


def missing_dirs(target: Path, base: Path) -> list[Path]:
    """Ordner, die für `target` (einen Ordner) noch angelegt werden müssen, von oben nach unten (unterhalb von `base`)."""
    out, p = [], target
    while p != base and p != p.parent and not p.exists():
        out.append(p)
        p = p.parent
    return out[::-1]


def make_dirs(target: Path, base: Path) -> list[Path]:
    """Legt fehlende Ordner an (für alle lesbar/schreibbar, wie sonst auch im NAS) und nennt die neu entstandenen."""
    new = missing_dirs(target, base)
    for d in new:
        d.mkdir(exist_ok=True)
        open_perms(d, True)
    return new


def copy_verify(src: Path, dst: Path, progress: Callable[[int], None] | None = None):
    """Kopiert über eine Teildatei, prüft die Größe und benennt erst dann um. Bei Fehlern bleibt kein halbes Ziel zurück."""
    tmp = dst.with_name("." + dst.name + ".mkw-part")
    done = 0
    try:
        with open(src, "rb") as fi, open(tmp, "wb") as fo:
            while chunk := fi.read(CHUNK):
                fo.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done)
        if tmp.stat().st_size != src.stat().st_size:
            raise OSError(f"Größe stimmt nach dem Kopieren nicht ({tmp.stat().st_size} statt {src.stat().st_size} Bytes)")
        if dst.exists():
            raise FileExistsError(str(dst))
        st = src.stat()
        os.utime(tmp, (st.st_atime, st.st_mtime))
        os.replace(tmp, dst)
        open_perms(dst, False)
    finally:
        tmp.unlink(missing_ok=True)


def move_file(src: Path, dst: Path, action: str = "verschieben", progress: Callable[[int], None] | None = None) -> str:
    """Rückgabe: 'rename' (umbenannt), 'copy' (kopiert, Original entfernt) oder 'copy-keep' (kopiert, Original bleibt)."""
    if dst.exists():
        raise FileExistsError(f"{dst.name} existiert schon")
    if action == "verschieben" and same_device(src, dst):
        os.rename(src, dst)
        return "rename"
    copy_verify(src, dst, progress)
    if action != "verschieben":
        return "copy-keep"
    try:
        src.unlink()
    except OSError as e:
        raise OSError(f"Kopie liegt im Ziel, das Original konnte nicht entfernt werden: {e}") from e
    return "copy"


def prune_empty(start: Path, stop: Path) -> list[Path]:
    """Leere Ordner von `start` aufwärts entfernen, nie `stop` selbst oder darüber. Rückgabe: entfernte Ordner."""
    removed = []
    p = start
    stop = stop.resolve()
    while p != stop and stop in p.resolve().parents:
        try:
            p.rmdir()
        except OSError:
            break
        removed.append(p)
        p = p.parent
    return removed
