"""Dateien einer Auswahl einsammeln (Ordner werden aufgelöst) und Laufzeit sowie Begleitdaten dazu holen."""
import asyncio
import os
from pathlib import Path

from app import files
from app.config import LIB_EXT
from app.media import store

MAX_FILES = 300
_sem = asyncio.Semaphore(3)


def expand(paths: list[str]) -> list[str]:
    """Pfade (Dateien oder Ordner, relativ zum Ausgabeordner) -> Liste der Videodateien, sortiert, ohne Doppelte."""
    base = files.out_dir()[0].resolve()
    out: list[str] = []
    for rel in paths:
        p = files.inside_out(rel)
        if p.is_file() and p.suffix.lower() in LIB_EXT:
            out.append(str(p.relative_to(base)))
        elif p.is_dir():
            for root, dirs, fs in os.walk(p):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                out += [str(Path(root, f).relative_to(base)) for f in sorted(fs) if f.lower().endswith(LIB_EXT) and not f.startswith(".")]
    seen: set[str] = set()
    return [x for x in out if not (x in seen or seen.add(x))][:MAX_FILES]


async def duration(rel: str, size: int) -> float:
    """Laufzeit in Sekunden: aus der Begleitdatei beim Rippen, dem Bibliotheks-Zwischenspeicher, sonst per ffprobe (höchstens drei gleichzeitig). 0 = unbekannt."""
    sc = store.sidecar(rel)
    if sc and sc["title"].get("duration"):                  # echte Laufzeit der Disc (die Datei selbst kann gekürzt sein)
        return float(sc["title"]["duration"])
    from app import library
    c = library.lib_cache.get(rel)
    if c and c.get("size") == size and c.get("info"):
        return float(c["info"].get("dur") or 0)
    from app.ffmpeg import probe
    async with _sem:
        try:
            pr = await probe(files.inside_out(rel))
            return float(pr["format"].get("duration") or 0)
        except (OSError, KeyError, ValueError):
            return 0.0


async def describe(paths: list[str]) -> list[dict]:
    """[{path, size, dur, disc?, title_id?}] für `detect.detect`."""
    rels = expand(paths)
    sizes = [files.inside_out(r).stat().st_size for r in rels]
    durs = await asyncio.gather(*(duration(r, s) for r, s in zip(rels, sizes)))
    out = []
    for rel, size, dur in zip(rels, sizes, durs):
        f = {"path": rel, "size": size, "dur": dur}
        sc = store.sidecar(rel)
        if sc:
            f.update(disc=sc["disc"], title_id=sc["title"].get("id"))
        out.append(f)
    return out
