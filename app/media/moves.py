"""Move or copy files safely: never overwrite, copy with a size check, clean up empty folders."""
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
    """Are the source and the (future) target on the same file system? Then renaming is enough."""
    try:
        return src.stat().st_dev == nearest_existing(dst.parent).stat().st_dev
    except OSError:
        return False


def missing_dirs(target: Path, base: Path) -> list[Path]:
    """Folders that still have to be created for `target` (a folder), from top to bottom (below `base`)."""
    out, p = [], target
    while p != base and p != p.parent and not p.exists():
        out.append(p)
        p = p.parent
    return out[::-1]


def make_dirs(target: Path, base: Path) -> list[Path]:
    """Creates missing folders (readable/writable for everyone, as elsewhere on the NAS) and returns the newly created ones."""
    new = missing_dirs(target, base)
    for d in new:
        d.mkdir(exist_ok=True)
        open_perms(d, True)
    return new


def copy_verify(src: Path, dst: Path, progress: Callable[[int], None] | None = None):
    """Copies via a partial file, checks the size and only then renames. On errors no half target is left behind."""
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
            raise OSError(f"Size does not match after copying ({tmp.stat().st_size} instead of {src.stat().st_size} bytes)")
        if dst.exists():
            raise FileExistsError(str(dst))
        st = src.stat()
        os.utime(tmp, (st.st_atime, st.st_mtime))
        os.replace(tmp, dst)
        open_perms(dst, False)
    finally:
        tmp.unlink(missing_ok=True)


def move_file(src: Path, dst: Path, action: str = "verschieben", progress: Callable[[int], None] | None = None) -> str:     # action "verschieben" = move
    """Returns: 'rename' (renamed), 'copy' (copied, original removed) or 'copy-keep' (copied, original stays)."""
    if dst.exists():
        raise FileExistsError(f"{dst.name} already exists")
    if action == "verschieben" and same_device(src, dst):
        os.rename(src, dst)
        return "rename"
    copy_verify(src, dst, progress)
    if action != "verschieben":
        return "copy-keep"
    try:
        src.unlink()
    except OSError as e:
        raise OSError(f"The copy is in the target, the original could not be removed: {e}") from e
    return "copy"


def prune_empty(start: Path, stop: Path) -> list[Path]:
    """Remove empty folders from `start` upwards, never `stop` itself or above it. Returns: the removed folders."""
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
