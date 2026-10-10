"""Kleine, abhängigkeitsfreie Hilfsfunktionen."""
import os
import re
from pathlib import Path

from fastapi import HTTPException


def safe_name(s: str, fallback="Disc") -> str:
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", s or "").strip(" .")
    s = s.replace("..", "_")
    return s[:120] or fallback


def fmt_bytes(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.1f} {u}" if u != "B" else f"{int(n)} B"
        n /= 1024


def hms_to_sec(t: str) -> int:
    try:
        h, m, s = (int(x) for x in t.split(":"))
        return h * 3600 + m * 60 + s
    except ValueError:
        return 0


def unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    i = 2
    while p.with_name(f"{p.stem} ({i}){p.suffix}").exists():
        i += 1
    return p.with_name(f"{p.stem} ({i}){p.suffix}")


def tree_size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def open_perms(p: Path, is_dir: bool):
    """Neu angelegte Dateien/Ordner für alle Nutzer lesbar/schreibbar machen (NFS- und SMB-Clients teilen sich das NAS,
    z. B. SMB-Gast `nobody` und NFS-Benutzer – sonst kann der jeweils andere sie nicht löschen)."""
    try:
        os.chmod(p, 0o777 if is_dir else 0o666)
    except OSError:
        pass


def mkdir_open(path: Path, base: Path):
    missing = []
    p = path
    while p != base and p != p.parent and not p.exists():
        missing.append(p)
        p = p.parent
    path.mkdir(parents=True, exist_ok=True)
    for m in missing:
        open_perms(m, True)


def valid_name(name: str) -> str:
    """Neuer Datei-/Ordnername: nur ein Name (kein Pfad), nicht versteckt, keine Steuerzeichen."""
    n = name.strip()
    if not n or n in (".", "..") or "/" in n or "\\" in n or n.startswith(".") or len(n) > 200 or re.search(r"[\x00-\x1f]", n):
        raise HTTPException(400, "Ungültiger Name (kein Pfad, nicht leer, nicht mit Punkt beginnend, höchstens 200 Zeichen).")
    return n
