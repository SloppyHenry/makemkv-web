"""MakeMKV-Web: headless MakeMKV mit Browser-Oberfläche.

- erkennt Laufwerke (/dev/sr*) und eingelegte Discs live (ioctl, kein Eingriff in laufende Jobs)
- analysiert neu eingelegte Discs automatisch (makemkvcon info)
- rippt gewählte Titel als MKV oder macht ein entschlüsseltes Disc-Backup
- Ausgabe nach /mnt/nas/rips, solange eingehängt (sonst lokaler Fallback)
"""
import asyncio
import base64
import copy
import errno
import secrets
import signal
import socket
import fcntl
import glob
import json
import os
import re
import shutil
import time
import urllib.request
from collections import deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

DATA = Path(os.environ.get("DATA_DIR", "/data"))
OUT_PREFERRED = Path(os.environ.get("OUTPUT_DIR", "/mnt/nas/rips"))
OUT_MOUNT = os.environ.get("OUTPUT_MOUNT", "/mnt/nas")
OUT_FALLBACK = Path(os.environ.get("FALLBACK_DIR", str(DATA / "output")))
INSTANCE = os.environ.get("INSTANCE_NAME") or socket.gethostname()
PEERS_RAW = os.environ.get("PEERS", "")      # „name=http://host:8780,name=…“ – die anderen MakeMKV-Web-Rechner (für die Übergabe)
MKV_DIR = DATA / ".MakeMKV"
CONFIG = DATA / "config.json"
BETAKEY = DATA / "betakey.json"
FORUM_URL = "https://forum.makemkv.com/forum/viewtopic.php?f=5&t=1053"

SEG_MIN_SECONDS = 600       # kürzere Titel werden nicht in Segmente geteilt


def choose_segments(dur: float) -> tuple[int, str]:
    """Entscheidet pro Konvertierung, ob (und in wie viele Segmente) geteilt wird – nach tatsächlich freien Kernen und freiem RAM.
    Einstellung conv_segments: 0 = automatisch, 1 = nie teilen, >1 = fest."""
    fixed = int(settings.get("conv_segments", 0))
    if dur < SEG_MIN_SECONDS:
        return 1, "kurzer Titel"
    if fixed >= 1:
        return fixed, "fest eingestellt" if fixed > 1 else "Segmentierung aus"
    cores = os.cpu_count() or 4
    try:
        free_cores = max(0.0, cores - os.getloadavg()[0])
    except OSError:
        free_cores = cores / 2
    try:
        with open("/proc/meminfo") as f:
            mem_gb = next(int(l.split()[1]) for l in f if l.startswith("MemAvailable")) / 1048576
    except (OSError, StopIteration, ValueError):
        mem_gb = 4.0
    n = int(min(free_cores // 4, mem_gb // 2.5, 8))            # ~4 Kerne und ~2,5 GB RAM je Segment
    reason = f"auto: {cores} Kerne, ca. {free_cores:.0f} frei, {mem_gb:.0f} GB RAM frei"
    return (n, reason) if n >= 2 else (1, reason)


X265_PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow")
# Vorgaben für „sieht aus wie das Original, braucht aber nur einen Bruchteil des Platzes“
CONVERT_DEFAULT = {"convert": False, "rf": 21, "preset": "slow", "tune": "none", "extra": "aq-mode=3:no-sao=1", "audio": "copy"}
PRESET_DEFAULTS = {"bluray": {**CONVERT_DEFAULT, "convert": True}, "dvd": dict(CONVERT_DEFAULT)}

DEFAULTS = {
    "minlength": 120,      # Sekunden, kürzere Titel werden ignoriert
    "auto_scan": True,     # eingelegte Disc sofort analysieren
    "auto_eject": True,    # nach erfolgreichem Rip auswerfen
    "audio_langs": "",     # z.B. "deu,eng" – leer = alle
    "sub_langs": "",       # z.B. "deu"     – leer = alle
    "key": "",             # eigener MakeMKV-Key; leer = öffentlicher Beta-Key
    "conv_parallel": 1,                    # gleichzeitige Konvertierungen (mehrere Dateien)
    "conv_segments": 0,                    # Segmente je Film: 0 = automatisch nach freien Kernen/RAM, 1 = aus, >1 = fest
    "presets": PRESET_DEFAULTS,  # Konvertierungs-Preset je Disc-Art (in der Oberfläche änderbar)
}

# virtuelle Laufwerke (z. B. CDEmu, VMs) nicht anzeigen; Umgebungsvariable HIDE_DRIVES = Regex, leer = nichts ausblenden
HIDE_RE = re.compile(os.environ.get("HIDE_DRIVES", r"cdemu|virtual|qemu|vbox"), re.I) if os.environ.get("HIDE_DRIVES", "x") else None
hidden_drives: set[str] = set()

CDROM_EJECT, CDROM_CLOSE_TRAY, CDROM_DRIVE_STATUS = 0x5309, 0x5319, 0x5326
CDS_NO_DISC, CDS_TRAY_OPEN, CDS_NOT_READY, CDS_DISC_OK = 1, 2, 3, 4

AUTH_USER = os.environ.get("AUTH_USER", "")
AUTH_PASS = os.environ.get("AUTH_PASS", "")    # leer = keine Anmeldung

app = FastAPI(title="MakeMKV-Web")


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    if AUTH_PASS:
        ok = False
        h = request.headers.get("authorization", "")
        if h.startswith("Basic "):
            try:
                u, _, p = base64.b64decode(h[6:]).decode().partition(":")
                ok = secrets.compare_digest(u.encode(), AUTH_USER.encode()) and secrets.compare_digest(p.encode(), AUTH_PASS.encode())
            except Exception:  # noqa: BLE001
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="MakeMKV-Web"'})
    return await call_next(request)
settings = copy.deepcopy(DEFAULTS)
drives: dict[str, "Drive"] = {}
clients: set[asyncio.Queue] = set()
beta = {"key": "", "fetched": 0, "error": ""}


# ---------------------------------------------------------------- Hilfsfunktionen
def clean_convert(c: dict) -> dict:
    """Prüft/ergänzt eine Konvertierungs-Konfiguration (kommt aus dem Browser)."""
    d = dict(CONVERT_DEFAULT)
    c = c if isinstance(c, dict) else {}
    d["convert"] = bool(c.get("convert", d["convert"]))
    try:
        d["rf"] = max(14, min(30, int(c.get("rf", d["rf"]))))
    except (TypeError, ValueError):
        pass
    if c.get("preset") in X265_PRESETS:
        d["preset"] = c["preset"]
    if c.get("tune") in ("none", "grain", "film", "animation", "stillimage"):
        d["tune"] = c["tune"]
    extra = str(c.get("extra", d["extra"])).strip()
    d["extra"] = extra if re.fullmatch(r"[A-Za-z0-9_=:.,\-]*", extra) else CONVERT_DEFAULT["extra"]
    if c.get("audio") in ("copy", "ac3", "eac3", "aac", "opus"):
        d["audio"] = c["audio"]
    return d


def load_settings():
    try:
        settings.update({k: v for k, v in json.loads(CONFIG.read_text()).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    settings["conv_parallel"] = max(1, min(int(settings.get("conv_parallel") or 1), 8))
    settings["conv_segments"] = max(0, min(int(settings.get("conv_segments") or 0), 12))
    saved = settings.get("presets") if isinstance(settings.get("presets"), dict) else {}
    settings["presets"] = {k: clean_convert({**PRESET_DEFAULTS[k], **(saved.get(k) or {})}) for k in PRESET_DEFAULTS}
    try:
        beta.update(json.loads(BETAKEY.read_text()))
    except (OSError, ValueError):
        pass


def save_settings():
    DATA.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(settings, indent=2))


def broadcast():
    for q in list(clients):
        if q.empty():
            q.put_nowait(1)


def safe_name(s: str, fallback="Disc") -> str:
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", s or "").strip(" .")
    s = s.replace("..", "_")
    return s[:120] or fallback


def mount_ok() -> bool:
    """True, wenn OUT_MOUNT ein echter NFS/CIFS-Mount ist (autofs wird dabei angestoßen)."""
    try:
        os.listdir(OUT_MOUNT)
        with open("/proc/self/mountinfo") as f:
            for line in f:
                p = line.split()
                if p[4] == OUT_MOUNT:
                    fstype = p[p.index("-") + 1]
                    if fstype.startswith(("nfs", "cifs", "fuse")):
                        return True
    except OSError:
        pass
    return False


def out_dir() -> tuple[Path, bool]:
    if mount_ok():
        try:
            OUT_PREFERRED.mkdir(parents=True, exist_ok=True)
            if os.access(OUT_PREFERRED, os.W_OK):
                return OUT_PREFERRED, True
        except OSError:
            pass
    OUT_FALLBACK.mkdir(parents=True, exist_ok=True)
    return OUT_FALLBACK, False


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


def drive_name(dev: str) -> str:
    base = Path(dev).name
    try:
        v = Path(f"/sys/class/block/{base}/device/vendor").read_text().strip()
        m = Path(f"/sys/class/block/{base}/device/model").read_text().strip()
        return f"{v} {m}".strip()
    except OSError:
        return base


def drive_status(dev: str) -> str:
    try:
        fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return "gone"
    try:
        r = fcntl.ioctl(fd, CDROM_DRIVE_STATUS, 0)
    except OSError:
        return "loading"
    finally:
        os.close(fd)
    return {CDS_NO_DISC: "empty", CDS_TRAY_OPEN: "open", CDS_NOT_READY: "loading", CDS_DISC_OK: "ready"}.get(r, "loading")


def tray(dev: str, req: int):
    fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
    try:
        fcntl.ioctl(fd, req, 0)
    finally:
        os.close(fd)


def selection_string() -> str:
    a = [x for x in re.split(r"[,\s]+", settings["audio_langs"].lower()) if re.fullmatch(r"[a-z]{3}", x)]
    s = [x for x in re.split(r"[,\s]+", settings["sub_langs"].lower()) if re.fullmatch(r"[a-z]{3}", x)]
    if not a and not s:
        return "-sel:all,+sel:all"
    parts = ["-sel:all", "+sel:video"]
    parts += [f"+sel:(audio&{x})" for x in a] + ["+sel:(audio&und)", "+sel:(audio&nolang)"] if a else ["+sel:audio"]
    parts += [f"+sel:(subtitle&{x})" for x in s] + ["+sel:(subtitle&und)", "+sel:(subtitle&nolang)"] if s else ["+sel:subtitle"]
    return ",".join(parts)


def write_makemkv_conf():
    key = settings["key"].strip() or beta["key"]
    MKV_DIR.mkdir(parents=True, exist_ok=True)
    lines = []
    if key:
        lines.append(f'app_Key = "{key}"')
    lines.append(f'app_DefaultSelectionString = "{selection_string()}"')
    lines.append('app_DefaultOutputFileName = "{NAME1}"')
    (MKV_DIR / "settings.conf").write_text("\n".join(lines) + "\n")


def fetch_beta_key_sync():
    try:
        req = urllib.request.Request(FORUM_URL, headers={"User-Agent": "Mozilla/5.0 makemkv-web"})
        html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
        m = re.search(r"<code>(T-[A-Za-z0-9@_\-]{40,})</code>", html)
        if not m:
            raise ValueError("Key nicht auf der Forumsseite gefunden")
        beta.update(key=m.group(1), fetched=int(time.time()), error="")
        BETAKEY.write_text(json.dumps(beta))
        return True
    except Exception as e:  # noqa: BLE001
        beta["error"] = str(e)
        return False


# ---------------------------------------------------------------- Laufwerk
class Drive:
    def __init__(self, dev: str):
        self.dev = dev
        self.name = drive_name(dev)
        self.status = "unknown"
        self.ready_polls = 0
        self.attempted = False    # für diese Disc wurde ein Scan versucht
        self.scan_id = 0
        self.disc = None
        self.label = ""
        self.error = ""
        self.job = None
        self.proc = None
        self.cancel = False
        self.log = deque(maxlen=300)
        self.last_msg = ("", 0)

    @property
    def busy(self):
        return self.job is not None

    def add_log(self, text: str, level="info"):
        if self.last_msg[0] == text:
            n = self.last_msg[1] + 1
            self.last_msg = (text, n)
            if n in (2, 10, 100, 1000):
                self.log.append({"t": time.strftime("%H:%M:%S"), "l": level, "m": f"… (×{n}) {text}"})
            return
        self.last_msg = (text, 1)
        self.log.append({"t": time.strftime("%H:%M:%S"), "l": level, "m": text})

    def public(self):
        return {
            "id": Path(self.dev).name, "dev": self.dev, "name": self.name, "status": self.status,
            "scan_id": self.scan_id, "disc": self.disc, "label": self.label, "error": self.error,
            "job": self.job, "log": list(self.log)[-120:],
        }


MSG_RE = re.compile(r'^MSG:(\d+),(\d+),(\d+),"(.*?)",".*$')
INFO_RE = {
    "C": re.compile(r'^CINFO:(\d+),(\d+),"(.*)"$'),
    "T": re.compile(r'^TINFO:(\d+),(\d+),(\d+),"(.*)"$'),
    "S": re.compile(r'^SINFO:(\d+),(\d+),(\d+),(\d+),"(.*)"$'),
}


class Parser:
    """Liest den makemkvcon-Robot-Modus."""

    def __init__(self, drive: Drive, job: dict):
        self.d, self.job = drive, job
        self.cinfo, self.tinfo, self.sinfo = {}, {}, {}
        self.saved = None
        self.errors = []

    def line(self, line: str):
        d, job = self.d, self.job
        if line.startswith("MSG:"):
            m = MSG_RE.match(line)
            if m:
                code, text = int(m.group(1)), m.group(4)
                level = "error" if 2000 <= code < 3000 or code in (5010, 5037) else "info"
                if code == 5074:    # Update-Hinweis
                    return
                if level == "error":
                    self.errors.append(text)
                d.add_log(text, level)
                if code in (5036, 5037):
                    self.saved = text
        elif line.startswith("PRGV:"):
            try:
                cur, total, mx = (int(x) for x in line[5:].split(","))
                if mx:
                    job["cur"], job["total"] = cur / mx, total / mx
            except ValueError:
                pass
        elif line.startswith("PRGT:") or line.startswith("PRGC:"):
            m = re.match(r'^PRG[TC]:\d+,\d+,"(.*)"$', line)
            if m:
                job["text" if line[3] == "T" else "sub"] = m.group(1)
        elif line.startswith("DRV:"):
            m = re.match(r'^DRV:\d+,\d+,\d+,\d+,"[^"]*","([^"]*)","([^"]*)"$', line)
            if m and m.group(2) == d.dev and m.group(1):
                d.label = m.group(1)
        elif line.startswith("CINFO:"):
            m = INFO_RE["C"].match(line)
            if m:
                self.cinfo[int(m.group(1))] = m.group(3)
        elif line.startswith("TINFO:"):
            m = INFO_RE["T"].match(line)
            if m:
                self.tinfo.setdefault(int(m.group(1)), {})[int(m.group(2))] = m.group(4)
        elif line.startswith("SINFO:"):
            m = INFO_RE["S"].match(line)
            if m:
                self.sinfo.setdefault((int(m.group(1)), int(m.group(2))), {})[int(m.group(3))] = m.group(5)

    def disc(self, minlength: int):
        titles = []
        for tid in sorted(self.tinfo):
            t = self.tinfo[tid]
            tracks = []
            for (ti, si), s in sorted(self.sinfo.items()):
                if ti != tid:
                    continue
                tracks.append({
                    "n": si, "type": s.get(1, ""), "codec": s.get(6, ""), "lang": s.get(29, ""),
                    "code": s.get(28, ""), "info": s.get(30, ""), "layout": s.get(40, ""),
                    "res": s.get(19, ""), "bitrate": s.get(13, ""),
                })
            secs = hms_to_sec(t.get(9, ""))
            titles.append({
                "id": tid, "name": t.get(2, f"Titel {tid}"), "duration": secs, "duration_text": t.get(9, ""),
                "bytes": int(t.get(11, "0") or 0), "size_text": t.get(10, ""),
                "chapters": int(t.get(8, "0") or 0), "source": t.get(16, ""), "outname": t.get(27, ""),
                "tracks": tracks,
            })
        return {
            "type": self.cinfo.get(1, "Disc"), "name": self.cinfo.get(2, "") or self.cinfo.get(32, ""),
            "volume": self.cinfo.get(32, ""), "titles": titles, "minlength": minlength,
        }


async def run_makemkv(drive: Drive, args: list[str], parser: Parser) -> int:
    write_makemkv_conf()
    env = {**os.environ, "HOME": str(DATA)}
    proc = await asyncio.create_subprocess_exec(
        "makemkvcon", "-r", "--cache=256", "--progress=-same", *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=env, limit=2**22,
    )
    drive.proc = proc
    last = 0.0
    try:
        async for raw in proc.stdout:
            parser.line(raw.decode("utf-8", "replace").rstrip())
            now = time.monotonic()
            if now - last > 0.3:
                last = now
                broadcast()
        return await proc.wait()
    finally:
        drive.proc = None


def device_lost(p: "Parser", drive: Drive) -> bool:
    """Das USB-Laufwerk hat sich während des Laufs zurückgesetzt/getrennt."""
    return any("SG:<unknown>" in e or "No such device" in e for e in p.errors) or drive_status(drive.dev) == "gone"


async def wait_ready(drive: Drive, timeout=60) -> bool:
    end = time.monotonic() + timeout
    await asyncio.sleep(2)
    while time.monotonic() < end:
        if await asyncio.to_thread(drive_status, drive.dev) == "ready":
            await asyncio.sleep(2)
            return True
        await asyncio.sleep(1.5)
    return False


async def do_scan(drive: Drive):
    drive.attempted = True
    drive.scan_id += 1
    drive.disc, drive.error = None, ""
    drive.log.clear()
    drive.last_msg = ("", 0)
    drive.job = {"kind": "scan", "text": "Disc wird analysiert …", "cur": 0, "total": 0, "started": time.time()}
    broadcast()
    ml = int(settings["minlength"])
    try:
        if not (settings["key"].strip() or beta["key"]):
            drive.job["text"] = "Hole MakeMKV-Beta-Key …"
            broadcast()
            await asyncio.to_thread(fetch_beta_key_sync)
        for attempt in range(3):
            p = Parser(drive, drive.job)
            rc = await run_makemkv(drive, [f"--minlength={ml}", "info", f"dev:{drive.dev}"], p)
            if drive.cancel:
                drive.error = "Analyse abgebrochen"
                break
            if p.tinfo:
                drive.disc = p.disc(ml)
                if not drive.disc["name"]:
                    drive.disc["name"] = drive.label
                drive.error = ""
                break
            if attempt < 2 and device_lost(p, drive):
                drive.add_log("Laufwerk hat sich zurückgesetzt – warte und versuche es erneut …", "error")
                drive.job.update(text="Laufwerk wird neu verbunden …", cur=0, total=0)
                broadcast()
                if await wait_ready(drive):
                    drive.log.clear()
                    drive.last_msg = ("", 0)
                    drive.job.update(text="Disc wird analysiert …")
                    continue
            drive.error = next((e for e in reversed(p.errors) if "No such device" not in e and "SG:<unknown>" not in e), "") \
                or f"Keine Titel gefunden (Exit-Code {rc}). Disc beschädigt, nicht unterstützt oder Key abgelaufen?"
            break
    except Exception as e:  # noqa: BLE001
        drive.error = f"Analyse fehlgeschlagen: {e}"
    finally:
        drive.cancel = False
        drive.job = None
        broadcast()


class RipTitle(BaseModel):
    id: int
    name: str = ""


class RipReq(BaseModel):
    titles: list[RipTitle] = []
    folder: str = ""
    mode: str = "mkv"    # mkv | backup
    convert: dict | None = None   # Konvertierung nach dem Rippen (nur mkv)


def unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    i = 2
    while p.with_name(f"{p.stem} ({i}){p.suffix}").exists():
        i += 1
    return p.with_name(f"{p.stem} ({i}){p.suffix}")


# ---------------------------------------------------------------- Zwischenspeicher + Übertragung
STAGING = Path(os.environ.get("STAGING_DIR", str(DATA / "staging")))
WORK, READY = STAGING / ".work", STAGING / "ready"     # WORK: läuft gerade, READY: fertig, wartet auf Übertragung
uploads: list[dict] = []
upload_queue: asyncio.Queue = asyncio.Queue()
_up_seq = 0
ACTIVE = ("queued", "copying", "retry")


def staging_free() -> int:
    STAGING.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(STAGING).free


def tree_size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def enqueue_upload(src: Path, rel: str, dev: str = "", replace: bool = False, lock: str = "", orig_size: int = 0, then_convert: dict | None = None):
    global _up_seq
    _up_seq += 1
    item = {"id": _up_seq, "name": rel, "src": str(src), "size": tree_size(src), "copied": 0, "speed": 0.0, "eta": 0,
            "status": "queued", "error": "", "dev": dev, "t": time.time(), "replace": replace, "lock": lock, "orig_size": orig_size, "then_convert": then_convert}
    uploads.append(item)
    upload_queue.put_nowait(item)
    broadcast()


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
                    await hand_to_peer_after_upload(item, base, dr)
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
                    cfg = clean_convert(json.loads(side.read_text()))
                except (OSError, ValueError):
                    cfg = None
                if cfg and cfg["convert"]:
                    enqueue_convert(f, folder.name, cfg)
                else:
                    release_original({"src": str(f), "folder": folder.name, "dev": ""})
    READY.mkdir(parents=True, exist_ok=True)
    for folder in sorted(READY.iterdir()):
        if folder.is_dir():
            entries = list(folder.iterdir())
            for e in entries:
                if not e.name.endswith(".part"):
                    enqueue_upload(e, f"{folder.name}/{e.name}")
            if not entries:
                folder.rmdir()



# ---------------------------------------------------------------- Konvertierung (ffmpeg, x265 10-bit, Software)
CONVERT, CONV_WORK = STAGING / "convert", STAGING / ".conv"
conversions: list[dict] = []
convert_queue: asyncio.Queue = asyncio.Queue()
conv_procs: dict[int, list] = {}
conv_state = {"paused": False}      # Konvertierung angehalten (ffmpeg per SIGSTOP, Warteschlange wartet)


def _signal_all(procs: list, sig: int):
    for pr in procs:
        if pr.returncode is None:
            try:
                pr.send_signal(sig)
            except ProcessLookupError:
                pass


def set_conv_paused(paused: bool):
    """Alle laufenden ffmpeg-Prozesse anhalten bzw. fortsetzen; neue Aufträge starten erst nach dem Fortsetzen."""
    conv_state["paused"] = paused
    for procs in conv_procs.values():
        _signal_all(procs, signal.SIGSTOP if paused else signal.SIGCONT)
    for c in conversions:
        if c["status"] == "running":
            c["paused"] = paused


def apply_pause(procs: list):
    """Frisch gestartete Prozesse sofort anhalten, wenn gerade pausiert ist."""
    if conv_state["paused"]:
        _signal_all(procs, signal.SIGSTOP)
_cv_seq = 0
CV_ACTIVE = ("queued", "running")


class SkipConversion(Exception):
    pass


def enqueue_convert(src: Path, folder: str, cfg: dict, dev: str = ""):
    global _cv_seq
    _cv_seq += 1
    src.with_name(src.name + ".json").write_text(json.dumps(cfg))
    conversions.append({"id": _cv_seq, "name": f"{folder}/{src.name}", "folder": folder, "src": str(src), "size_in": src.stat().st_size,
                        "size_out": 0, "status": "queued", "pct": 0.0, "fps": 0.0, "speed": 0.0, "eta": 0, "error": "",
                        "cfg": cfg, "dev": dev, "t": time.time(), "started": 0, "mode": "", "origin": "", "paused": False, "handed": ""})
    convert_queue.put_nowait(conversions[-1])
    broadcast()


async def probe(path: Path) -> dict:
    p = await asyncio.create_subprocess_exec("ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path),
                                             stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await p.communicate()
    if p.returncode:
        raise OSError("ffprobe: " + err.decode(errors="replace")[-300:])
    return json.loads(out)


async def detect_crop(src: Path, dur: float, w: int, h: int):
    """Schwarze Balken automatisch erkennen (5 Stichproben, größter gemeinsamer Bildbereich)."""
    boxes = []
    for f in (0.1, 0.3, 0.5, 0.7, 0.9):
        p = await asyncio.create_subprocess_exec("nice", "-n", "10", "ffmpeg", "-hide_banner", "-nostdin", "-ss", str(int(dur * f)), "-i", str(src),
                                                 "-t", "8", "-vf", "cropdetect=limit=24:round=2:reset=0", "-an", "-sn", "-f", "null", "-",
                                                 stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, err = await p.communicate()
        m = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", err.decode(errors="replace"))
        if m:
            boxes.append(tuple(int(x) for x in m[-1]))
    if not boxes:
        return None
    x1, y1 = min(b[2] for b in boxes), min(b[3] for b in boxes)
    x2, y2 = max(b[2] + b[0] for b in boxes), max(b[3] + b[1] for b in boxes)
    cw, ch = (x2 - x1) // 2 * 2, (y2 - y1) // 2 * 2
    if cw <= 0 or ch <= 0 or (cw, ch) == (w, h) or cw * ch < w * h * 0.5:
        return None
    return f"crop={cw}:{ch}:{x1}:{y1}"


def x265_args(cfg: dict, pools: int = 0) -> list[str]:
    a = ["-c:v", "libx265", "-preset", cfg["preset"], "-crf", str(cfg["rf"]), "-pix_fmt", "yuv420p10le"]
    if cfg["tune"] in ("grain", "animation"):          # film/stillimage: x265 kennt dazu keinen Tune -> keiner gesetzt
        a += ["-tune", cfg["tune"]]
    params = ["log-level=error"] + ([f"pools={pools}"] if pools else []) + ([cfg["extra"]] if cfg["extra"] else [])
    return a + ["-x265-params", ":".join(params)]


def audio_args(cfg: dict, info: dict) -> list[str]:
    auds = [x for x in info["streams"] if x["codec_type"] == "audio"]
    if cfg["audio"] == "copy" or not auds:
        return ["-c:a", "copy"]
    a: list[str] = []
    for i, st in enumerate(auds):
        ch = int(st.get("channels") or 2)
        if cfg["audio"] == "aac":
            if ch > 6:
                a += [f"-ac:a:{i}", "6"]
            a += [f"-c:a:{i}", "aac", f"-b:a:{i}", "160k" if ch <= 2 else "256k"]
            layout = {1: "mono", 2: "stereo", 6: "5.1"}.get(min(ch, 6))
            if layout:
                a += [f"-filter:a:{i}", f"aformat=channel_layouts={layout}"]
        elif cfg["audio"] == "opus":
            layout = {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}.get(ch)
            a += [f"-c:a:{i}", "libopus", f"-b:a:{i}", "128k" if ch <= 2 else "320k" if ch <= 6 else "448k"]
            if layout:
                a += [f"-filter:a:{i}", f"aformat=channel_layouts={layout}"]
        else:
            if ch > 6:
                a += [f"-ac:a:{i}", "6"]
            a += [f"-c:a:{i}", cfg["audio"], f"-b:a:{i}", "192k" if ch <= 2 else "640k"]
    return a


def ffmpeg_args(src: Path, out: Path, cfg: dict, info: dict, crop) -> list[str]:
    a = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src), "-map", "0:v:0", "-map", "0:a?", "-map", "0:s?", "-map_chapters", "0"]
    if crop:
        a += ["-vf", crop]
    return a + x265_args(cfg) + ["-fps_mode", "cfr"] + audio_args(cfg, info) + ["-c:s", "copy", "-progress", "pipe:1", "-nostats", str(out)]


async def pump(proc, state: dict, key, tail: deque) -> int:
    """Liest die -progress-Ausgabe eines ffmpeg-Prozesses nach state[key] und sammelt die letzten Fehlerzeilen."""
    async def err():
        async for raw in proc.stderr:
            tail.append(raw.decode(errors="replace").strip())

    et = asyncio.create_task(err())
    try:
        async for raw in proc.stdout:
            k, _, val = raw.decode(errors="replace").strip().partition("=")
            st = state[key]
            try:
                if k == "out_time_us" and val.lstrip("-").isdigit():
                    st["t"] = int(val) / 1e6
                elif k == "fps":
                    st["fps"] = float(val or 0)
                elif k == "total_size" and val.isdigit():
                    st["size"] = int(val)
            except ValueError:
                pass
        return await proc.wait()
    finally:
        await et


async def aggregate(item: dict, state: dict, dur: float):
    """Fortschritt aller (Teil-)Prozesse zu einer Anzeige zusammenfassen."""
    t0 = time.monotonic()
    while True:
        if conv_state["paused"]:                      # Pausenzeit zählt nicht zur Laufzeit (Tempo/Restzeit)
            t0 += 0.8
            await asyncio.sleep(0.8)
            continue
        done = sum(s["t"] for s in state.values())
        el = max(1.0, time.monotonic() - t0)
        speed = done / el
        item.update(pct=max(0.0, min(0.97, done / dur)), fps=sum(s["fps"] for s in state.values()), speed=speed,
                    eta=max(0, (dur - done) / speed) if speed > 0.001 else 0, size_out=sum(s["size"] for s in state.values()))
        broadcast()
        await asyncio.sleep(0.8)


async def spawn(args: list[str]):
    return await asyncio.create_subprocess_exec("nice", "-n", "10", *args, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE, limit=2**20)


async def convert_single(item, src, cfg, info, dur, crop, out):
    proc = await spawn(ffmpeg_args(src, out, cfg, info, crop))
    conv_procs[item["id"]] = [proc]
    apply_pause([proc])
    state, tail = {0: {"t": 0.0, "fps": 0.0, "size": 0}}, deque(maxlen=12)
    agg = asyncio.create_task(aggregate(item, state, dur))
    try:
        rc = await pump(proc, state, 0, tail)
    finally:
        agg.cancel()
        conv_procs.pop(item["id"], None)
    if item["status"] == "skipped":
        out.unlink(missing_ok=True)
        raise SkipConversion()
    if rc != 0 or not out.exists():
        out.unlink(missing_ok=True)
        raise OSError("ffmpeg fehlgeschlagen: " + " | ".join(list(tail)[-4:]))


async def convert_segments(item, src, cfg, info, dur, crop, nseg, out):
    """Film in Zeitabschnitte teilen, parallel kodieren, danach mit Original-Audio/Untertiteln/Kapiteln zusammensetzen."""
    v = next(x for x in info["streams"] if x["codec_type"] == "video")
    num, den = (int(x) for x in v["r_frame_rate"].split("/"))
    fps = num / den
    total = round(dur * fps)
    bounds = [round(total * i / nseg) for i in range(nseg + 1)]
    work = CONV_WORK / f"{item['id']}-seg"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    pools = max(2, (os.cpu_count() or 4) // nseg)
    vf = (crop + "," if crop else "") + "setpts=PTS-STARTPTS"
    procs, tails, state = [], [], {}
    try:
        for i in range(nseg):
            a = ["ffmpeg", "-hide_banner", "-nostdin", "-y"]
            if i > 0:
                a += ["-ss", f"{(bounds[i] - 0.5) / fps:.6f}"]       # Schnitt auf halber Bildgrenze: eindeutig, ohne doppeltes/fehlendes Bild
            if i < nseg - 1:
                a += ["-to", f"{(bounds[i + 1] - 0.5) / fps:.6f}"]
            a += ["-i", str(src), "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", vf] + x265_args(cfg, pools) + \
                 ["-r", f"{num}/{den}", "-fps_mode", "cfr", "-progress", "pipe:1", "-nostats", str(work / f"seg{i:02d}.mkv")]
            procs.append(await spawn(a))
            tails.append(deque(maxlen=8))
            state[i] = {"t": 0.0, "fps": 0.0, "size": 0}
        conv_procs[item["id"]] = procs
        apply_pause(procs)
        agg = asyncio.create_task(aggregate(item, state, dur))
        try:
            rcs = await asyncio.gather(*[pump(p, state, i, tails[i]) for i, p in enumerate(procs)])
        finally:
            agg.cancel()
            conv_procs.pop(item["id"], None)
        if item["status"] == "skipped":
            raise SkipConversion()
        for i, rc in enumerate(rcs):
            if rc != 0:
                raise OSError(f"Segment {i + 1}/{nseg} fehlgeschlagen: " + " | ".join(list(tails[i])[-3:]))
        for i in range(nseg):                                        # jedes Segment muss die erwartete Länge haben
            want = (bounds[i + 1] - bounds[i]) / fps
            got = float((await probe(work / f"seg{i:02d}.mkv"))["format"]["duration"])
            if abs(got - want) > 2 / fps + 0.3:
                raise OSError(f"Segment {i + 1} hat falsche Länge ({got:.2f}s statt {want:.2f}s)")
        item.update(pct=0.98, eta=0, fps=0.0)
        broadcast()
        lst = work / "list.txt"
        lst.write_text("".join(f"file '{work}/seg{i:02d}.mkv'\n" for i in range(nseg)))
        mux = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(src),
               "-map", "0:v:0", "-map", "1:a?", "-map", "1:s?", "-map_chapters", "1", "-c:v", "copy"] + audio_args(cfg, info) + \
              ["-c:s", "copy", str(out)]
        p = await spawn(mux)
        conv_procs[item["id"]] = [p]
        apply_pause([p])
        _, err = await p.communicate()
        conv_procs.pop(item["id"], None)
        if item["status"] == "skipped":
            raise SkipConversion()
        if p.returncode != 0 or not out.exists():
            raise OSError("Zusammensetzen fehlgeschlagen: " + err.decode(errors="replace")[-300:])
        # Bildanzahl des Ergebnisses prüfen (±1 Bild je Schnittstelle toleriert)
        r = await asyncio.create_subprocess_exec("ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                                                 "stream=nb_read_packets", "-of", "csv=p=0", str(out),
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        o, _ = await r.communicate()
        frames = int(o.decode().strip().split(",")[0] or 0)
        if abs(frames - total) > nseg + 3:
            raise OSError(f"Bildanzahl stimmt nicht ({frames} statt ca. {total})")
    except BaseException:
        out.unlink(missing_ok=True)
        for pr in procs:
            if pr.returncode is None:
                pr.terminate()
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


async def convert_one(item: dict) -> Path:
    src, cfg = Path(item["src"]), item["cfg"]
    info = await probe(src)
    dur = float(info["format"]["duration"])
    v = next(x for x in info["streams"] if x["codec_type"] == "video")
    item.update(status="running", pct=0.0, fps=0.0, speed=0.0, eta=0, started=time.time())
    broadcast()
    crop = await detect_crop(src, dur, int(v["width"]), int(v["height"]))
    if item["status"] == "skipped":
        raise SkipConversion()
    if item.get("origin") == "library" and staging_free() < item["size_in"]:
        raise OSError(f"Zu wenig Platz im Zwischenspeicher für das Ergebnis ({fmt_bytes(staging_free())} frei)")
    nseg, why = choose_segments(dur) if item.get("attempt", 1) == 1 else (1, "zweiter Versuch")
    item["mode"] = (f"{nseg} Segmente parallel" if nseg > 1 else "ein Prozess") + f" ({why})"
    CONV_WORK.mkdir(parents=True, exist_ok=True)
    out = CONV_WORK / f"{item['id']}.mkv"
    if nseg > 1:
        await convert_segments(item, src, cfg, info, dur, crop, nseg, out)
    else:
        await convert_single(item, src, cfg, info, dur, crop, out)
    oi = await probe(out)
    od = float(oi["format"]["duration"])
    if abs(od - dur) > max(2.0, dur * 0.01):
        out.unlink(missing_ok=True)
        raise OSError(f"Ergebnis hat falsche Länge ({od:.0f}s statt {dur:.0f}s)")
    cnt = lambda pr, t: sum(1 for x in pr["streams"] if x["codec_type"] == t)      # noqa: E731
    if (cnt(info, "audio"), cnt(info, "subtitle")) != (cnt(oi, "audio"), cnt(oi, "subtitle")):
        out.unlink(missing_ok=True)
        raise OSError("Anzahl der Audio-/Untertitelspuren weicht vom Original ab")
    return out


# ---------------------------------------------------------------- Bibliothek (nachträglich konvertieren, Original ersetzen)
REPLACE_DIR = STAGING / "replace"        # fertig konvertiert, wartet auf das Zurückspielen (ersetzt das Original)
LIB_EXT = (".mkv", ".iso", ".m2ts")
LIB_CODECS = ("h264", "vc1", "mpeg2video", "mpeg4", "wmv3")     # diese werden als „Original“ angeboten
LOCK_TTL = 300                                                  # Sekunden ohne Herzschlag, danach gilt eine Sperre als verwaist
lib_cache: dict[str, dict] = {}
lib_probe_queue: asyncio.Queue = asyncio.Queue()
lib_probing: set[str] = set()
held_locks: set[str] = set()
LIBCACHE = DATA / "library.json"


def lock_path(p: Path) -> Path:
    return p.with_name("." + p.name + ".mkw-lock")


def acquire_lock(p: Path, takeover_from: str = "") -> str:
    """Sperrdatei neben der Datei anlegen (damit nicht zwei Instanzen dieselbe Datei umbauen). Rückgabe: '' = gesperrt, sonst Name des Besitzers."""
    lp = lock_path(p)
    for _ in range(2):
        try:
            fd = os.open(lp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
        except FileExistsError:
            try:
                if time.time() - lp.stat().st_mtime > LOCK_TTL:      # verwaist -> übernehmen
                    lp.unlink(missing_ok=True)
                    continue
                owner = json.loads(lp.read_text()).get("inst", "andere Instanz")
                if takeover_from and owner.lower() == takeover_from.lower():      # Übergabe: der bisherige Besitzer gibt ab
                    lp.unlink(missing_ok=True)
                    continue
            except (OSError, ValueError):
                owner = "andere Instanz"
            return owner
        with os.fdopen(fd, "w") as f:
            json.dump({"inst": INSTANCE, "t": time.time()}, f)
        open_perms(lp, False)
        held_locks.add(str(lp))
        return ""
    return "andere Instanz"


def release_lock(lp: str):
    if not lp:                       # Sperre wurde bei einer Übergabe abgegeben
        return
    held_locks.discard(lp)
    try:
        Path(lp).unlink(missing_ok=True)
    except OSError:
        pass


async def lock_heartbeat():
    while True:
        await asyncio.sleep(60)
        for lp in list(held_locks):
            try:
                os.utime(lp)
            except OSError:
                pass


def lib_info(pr: dict) -> dict:
    v = next((x for x in pr["streams"] if x["codec_type"] == "video"), {})
    auds = [x for x in pr["streams"] if x["codec_type"] == "audio"]
    return {"codec": v.get("codec_name", ""), "w": v.get("width", 0), "h": v.get("height", 0), "pix": v.get("pix_fmt", ""),
            "hdr": v.get("color_transfer") in ("smpte2084", "arib-std-b67"),
            "dur": float(pr["format"].get("duration") or 0),
            "audio": [f'{a.get("codec_name", "?")} {a.get("channels", "?")}ch {a.get("tags", {}).get("language", "")}'.strip() for a in auds],
            "subs": sum(1 for x in pr["streams"] if x["codec_type"] == "subtitle")}


def lib_state(info) -> str:
    if info is None:
        return "unknown"
    if info["hdr"]:
        return "hdr"
    if info["codec"] == "hevc":
        return "hevc"
    return "ok" if info["codec"] in LIB_CODECS else "other"


def save_libcache():
    try:
        LIBCACHE.write_text(json.dumps(lib_cache))
    except OSError:
        pass


async def lib_probe_worker():
    n = 0
    while True:
        rel = await lib_probe_queue.get()
        try:
            p = Path(out_cache["dir"]) / rel
            st = p.stat()
            try:
                lib_cache[rel] = {"size": st.st_size, "mtime": st.st_mtime, "info": lib_info(await probe(p))}
            except Exception as e:  # noqa: BLE001
                lib_cache[rel] = {"size": st.st_size, "mtime": st.st_mtime, "info": None, "err": str(e)[:120]}
            n += 1
            if n % 10 == 0 or lib_probe_queue.empty():
                save_libcache()
        except OSError:
            pass
        finally:
            lib_probing.discard(rel)


def scan_library():
    base, _ = out_dir()
    items, locks = [], {}
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        if len(Path(root).relative_to(base).parts) >= 4:
            dirs[:] = []
        for f in files:
            full = Path(root) / f
            if f.startswith(".") and f.endswith(".mkw-lock"):
                try:
                    locks[str((Path(root) / f[1:-len(".mkw-lock")]).relative_to(base))] = (full.stat().st_mtime, full)
                except OSError:
                    pass
                continue
            if f.startswith(".") or not f.lower().endswith(LIB_EXT):
                continue
            try:
                st = full.stat()
            except OSError:
                continue
            items.append({"path": str(full.relative_to(base)), "size": st.st_size, "mtime": st.st_mtime})
    return str(base), items, locks


def release_original(item: dict):
    """Original unverändert in die Übertragung geben (Konvertierung übersprungen/fehlgeschlagen) – nichts geht verloren."""
    src = Path(item["src"])
    if src.exists():
        rdir = READY / item["folder"]
        rdir.mkdir(parents=True, exist_ok=True)
        final = unique_path(rdir / src.name)
        os.replace(src, final)
        handover = item.get("handover")
        then = {**handover, "cfg": item["cfg"]} if handover else None     # nach der Übertragung beim anderen Rechner anmelden
        enqueue_upload(final, f"{item['folder']}/{final.name}", item["dev"], then_convert=then)
    src.with_name(src.name + ".json").unlink(missing_ok=True)
    try:
        src.parent.rmdir()
    except OSError:
        pass


conv_running = 0


def ensure_conv_workers():
    """So viele Konvertierungs-Worker laufen lassen, wie in den Einstellungen steht."""
    global conv_running
    while conv_running < int(settings["conv_parallel"]):
        conv_running += 1
        ensure_conv_workers()


async def convert_worker():
    global conv_running
    while True:
        if conv_running > int(settings["conv_parallel"]):      # Einstellung wurde verkleinert
            conv_running -= 1
            return
        item = await convert_queue.get()
        dr = drives.get(item["dev"])
        while conv_state["paused"] and item["status"] == "queued":      # pausiert: nichts Neues starten
            await asyncio.sleep(1)
        if item["status"] != "skipped":
            for attempt in (1, 2):
                try:
                    item["attempt"] = attempt
                    out = await convert_one(item)
                    if item.get("origin") == "library":          # Ergebnis ersetzt später das Original auf dem NAS
                        REPLACE_DIR.mkdir(parents=True, exist_ok=True)
                        dest_f = REPLACE_DIR / f"{item['id']}-{Path(item['rel']).name}"
                        os.replace(out, dest_f)
                        item.update(status="done", pct=1.0, eta=0, size_out=dest_f.stat().st_size, t=time.time())
                        enqueue_upload(dest_f, item["rel"], "", replace=True, lock=item["lock"], orig_size=item["size_in"])
                        break
                    src = Path(item["src"])
                    rdir = READY / item["folder"]
                    rdir.mkdir(parents=True, exist_ok=True)
                    final = unique_path(rdir / src.name)
                    os.replace(out, final)
                    size_in = item["size_in"]
                    src.unlink(missing_ok=True)
                    src.with_name(src.name + ".json").unlink(missing_ok=True)
                    try:
                        src.parent.rmdir()
                    except OSError:
                        pass
                    item.update(status="done", pct=1.0, eta=0, size_out=final.stat().st_size, t=time.time())
                    if dr:
                        dr.add_log(f"Konvertiert: {final.name} ({fmt_bytes(size_in)} → {fmt_bytes(item['size_out'])})", "ok")
                    enqueue_upload(final, f"{item['folder']}/{final.name}", item["dev"])
                    break
                except SkipConversion:
                    break
                except Exception as e:  # noqa: BLE001
                    item["error"] = str(e)[:400]
                    if dr:
                        dr.add_log(f"Konvertierung von {item['name']} fehlgeschlagen: {item['error']}", "error")
                    if attempt == 1:
                        item.update(status="queued", pct=0.0)
                        broadcast()
        if item["status"] != "done":
            was_skipped = item["status"] == "skipped"
            if item.get("origin") == "library":              # Original liegt unverändert auf dem NAS
                release_lock(item["lock"])
                item["status"] = "skipped" if was_skipped else "error"
                if not was_skipped:
                    item["error"] += " – Original bleibt unverändert"
                broadcast()
                continue
            release_original(item)
            item["status"] = "skipped" if was_skipped else "error"
            if not was_skipped:
                item["error"] += " – Original wird unverändert übertragen"
            if dr:
                dr.add_log(f"{item['name']}: Original wird unverändert übertragen", "info")
        broadcast()


async def wait_for_space(drive: Drive, job: dict, need: int):
    """Wartet, bis im Zwischenspeicher Platz ist (laufende Übertragungen geben Platz frei)."""
    while staging_free() < need:
        if not any(u["status"] in ACTIVE for u in uploads) and not any(c["status"] in CV_ACTIVE for c in conversions):
            raise OSError(f"Zu wenig Platz im Zwischenspeicher ({STAGING}): {fmt_bytes(staging_free())} frei, {fmt_bytes(need)} nötig")
        job.update(text="Warte auf Konvertierung/Übertragung (Platz im Zwischenspeicher) …", cur=0, total=0)
        broadcast()
        if drive.cancel:
            return
        await asyncio.sleep(5)


async def do_rip(drive: Drive, req: RipReq, dest: Path):
    disc = drive.disc
    by_id = {t["id"]: t for t in disc["titles"]}
    todo = [t for t in req.titles if t.id in by_id]
    backup = req.mode == "backup"
    cfg = clean_convert(req.convert) if (req.convert and not backup and req.convert.get("convert")) else None
    folder = dest.name
    total_bytes = sum(by_id[t.id]["bytes"] for t in todo) or 1
    job = {"kind": "backup" if backup else "rip", "text": "Starte …", "sub": "", "cur": 0, "total": 0,
           "overall": 0.0, "started": time.time(), "dest": str(dest), "index": 0, "count": 1 if backup else len(todo),
           "title": "", "done": [], "failed": 0, "bytes": total_bytes}
    drive.job = job
    drive.log.clear()
    drive.last_msg = ("", 0)
    drive.error = ""
    broadcast()
    ok = True
    work = WORK / f"{int(time.time())}-{Path(drive.dev).name}"
    try:
        work.mkdir(parents=True, exist_ok=True)
        if backup:
            await wait_for_space(drive, job, 55 * 2**30)
            bdir = work / folder
            bdir.mkdir()
            p = Parser(drive, job)
            tracker = asyncio.create_task(track_overall(job, lambda: job["total"]))
            rc = await run_makemkv(drive, ["backup", "--decrypt", f"dev:{drive.dev}", str(bdir)], p)
            tracker.cancel()
            ok = rc == 0 and not drive.cancel
            if ok:
                rd = unique_path(READY / folder)
                READY.mkdir(parents=True, exist_ok=True)
                os.replace(bdir, rd)
                for e in sorted(rd.iterdir()):
                    enqueue_upload(e, f"{folder}/{e.name}", drive.dev)
                job["done"].append({"name": folder + " (Disc-Backup)", "bytes": 0})
        else:
            done_bytes = 0
            for i, t in enumerate(todo):
                if drive.cancel:
                    ok = False
                    break
                info = by_id[t.id]
                await wait_for_space(drive, job, int(info["bytes"] * 1.05) + 2 * 2**30)
                if drive.cancel:
                    ok = False
                    break
                job.update(index=i + 1, title=t.name or info["name"], cur=0, total=0, text=f"Titel {i+1}/{len(todo)}")
                for x in work.glob("*.mkv"):
                    x.unlink(missing_ok=True)
                p = Parser(drive, job)
                base = done_bytes
                w = info["bytes"] or 1

                async def upd(base=base, w=w):
                    while True:
                        job["overall"] = min(1.0, (base + job["total"] * w) / total_bytes)
                        await asyncio.sleep(0.5)

                tracker = asyncio.create_task(upd())
                for attempt in range(3):
                    rc = await run_makemkv(drive, [f"--minlength={disc['minlength']}", "mkv", f"dev:{drive.dev}", str(t.id), str(work)], p)
                    new = sorted(work.glob("*.mkv"))
                    if drive.cancel or (rc == 0 and new) or attempt == 2 or not device_lost(p, drive):
                        break
                    for x in new:
                        x.unlink(missing_ok=True)
                    drive.add_log("Laufwerk hat sich zurückgesetzt – warte und versuche den Titel erneut …", "error")
                    job.update(text="Laufwerk wird neu verbunden …", cur=0, total=0)
                    broadcast()
                    if not await wait_ready(drive):
                        break
                    p = Parser(drive, job)
                tracker.cancel()
                if drive.cancel:
                    ok = False
                    break
                if rc != 0 or not new:
                    job["failed"] += 1
                    ok = False
                    for x in new:
                        x.unlink(missing_ok=True)
                    drive.add_log(f"Titel {t.id} fehlgeschlagen (Exit-Code {rc})", "error")
                    continue
                f = new[0]
                want = safe_name(t.name, "") if t.name.strip() else ""
                if cfg:                       # erst konvertieren, dann übertragen
                    cdir = CONVERT / folder
                    cdir.mkdir(parents=True, exist_ok=True)
                    final = unique_path(cdir / ((want or f.stem) + ".mkv"))
                    os.replace(f, final)
                    done_bytes += info["bytes"]
                    job["overall"] = min(1.0, done_bytes / total_bytes)
                    job["done"].append({"name": final.name, "bytes": final.stat().st_size})
                    drive.add_log(f"Fertig gerippt: {final.name} ({fmt_bytes(final.stat().st_size)}) – Konvertierung eingereiht", "ok")
                    enqueue_convert(final, folder, cfg, drive.dev)
                    continue
                rdir = READY / folder
                rdir.mkdir(parents=True, exist_ok=True)
                final = unique_path(rdir / ((want or f.stem) + ".mkv"))
                os.replace(f, final)          # fertig -> ab in die Warteschlange, Laufwerk liest schon den nächsten Titel
                done_bytes += info["bytes"]
                job["overall"] = min(1.0, done_bytes / total_bytes)
                job["done"].append({"name": final.name, "bytes": final.stat().st_size})
                drive.add_log(f"Fertig gerippt: {final.name} ({fmt_bytes(final.stat().st_size)}) – Übertragung läuft im Hintergrund", "ok")
                enqueue_upload(final, f"{folder}/{final.name}", drive.dev)
        if drive.cancel:
            drive.error = "Abgebrochen"
        elif not ok:
            drive.error = "Es sind Fehler aufgetreten – siehe Protokoll"
        else:
            drive.add_log("Alles fertig gerippt.", "ok")
    except Exception as e:  # noqa: BLE001
        drive.error = f"Rip fehlgeschlagen: {e}"
        ok = False
    finally:
        was_cancel = drive.cancel
        drive.cancel = False
        drive.job = None
        shutil.rmtree(work, ignore_errors=True)
        broadcast()
    if ok and not was_cancel and settings["auto_eject"]:
        await asyncio.sleep(1)
        try:
            tray(drive.dev, CDROM_EJECT)
            drive.add_log("Disc ausgeworfen.", "ok")
        except OSError as e:
            drive.add_log(f"Auswerfen fehlgeschlagen: {e}", "error")
        broadcast()


async def track_overall(job, get):
    while True:
        job["overall"] = get()
        await asyncio.sleep(0.5)


# ---------------------------------------------------------------- Hintergrund
async def poller():
    while True:
        try:
            devs = sorted(glob.glob("/dev/sr[0-9]*"))
            changed = False
            hidden_drives.intersection_update(devs)
            for d in devs:
                if d not in drives and d not in hidden_drives:
                    dr = Drive(d)
                    if HIDE_RE and HIDE_RE.search(dr.name):
                        hidden_drives.add(d)
                        continue
                    drives[d] = dr
                    changed = True
            for d, dr in list(drives.items()):
                if dr.busy:
                    continue
                if d not in devs:
                    del drives[d]
                    changed = True
                    continue
                st = await asyncio.to_thread(drive_status, d)
                if st == "gone":
                    continue
                if st != dr.status:
                    dr.status = st
                    changed = True
                    if st in ("empty", "open"):
                        dr.disc, dr.error, dr.label, dr.attempted, dr.ready_polls = None, "", "", False, 0
                        dr.log.clear()
                dr.ready_polls = dr.ready_polls + 1 if st == "ready" else 0
                if st == "ready" and dr.ready_polls >= 2 and not dr.attempted and settings["auto_scan"]:
                    asyncio.create_task(do_scan(dr))
                    changed = True
            if changed:
                broadcast()
        except Exception as e:  # noqa: BLE001
            print("poller:", e, flush=True)
        await asyncio.sleep(1.5)


async def key_refresher():
    while True:
        if not settings["key"].strip() and (not beta["key"] or time.time() - beta["fetched"] > 12 * 3600):
            await asyncio.to_thread(fetch_beta_key_sync)
            broadcast()
        await asyncio.sleep(1800)


@app.on_event("startup")
async def startup():
    DATA.mkdir(parents=True, exist_ok=True)
    load_settings()
    asyncio.create_task(poller())
    asyncio.create_task(key_refresher())
    asyncio.create_task(output_refresher())
    recover_staging()
    try:
        lib_cache.update(json.loads(LIBCACHE.read_text()))
    except (OSError, ValueError):
        pass
    asyncio.create_task(lib_probe_worker())
    asyncio.create_task(lock_heartbeat())
    if parse_peers(PEERS_RAW):
        asyncio.create_task(peer_prober())
    asyncio.create_task(upload_worker())
    asyncio.create_task(convert_worker())


# ---------------------------------------------------------------- API
out_cache = {"dir": str(OUT_FALLBACK), "mounted": False, "free": 0, "stalled": False}


def _probe_output():
    d, mounted = out_dir()
    return {"dir": str(d), "mounted": mounted, "free": shutil.disk_usage(d).free, "stalled": False}


async def output_refresher():
    """Ausgabeziel im Hintergrund prüfen – ein hängendes Netzlaufwerk darf die Oberfläche nicht blockieren."""
    while True:
        try:
            out_cache.update(await asyncio.wait_for(asyncio.to_thread(_probe_output), 8))
        except asyncio.TimeoutError:
            out_cache["stalled"] = True
        except OSError:
            out_cache["stalled"] = True
        await asyncio.sleep(5)


# ---------------------------------------------------------------- Peers und Übergabe
peers_state: dict[str, dict] = {}


def parse_peers(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in raw.split(","):
        name, _, url = part.strip().partition("=")
        name, url = name.strip(), url.strip().rstrip("/")
        if name and re.fullmatch(r"https?://[A-Za-z0-9.\-\[\]:]+", url) and name.lower() != INSTANCE.lower():
            out[name] = url
    return out


def capacity() -> dict:
    try:
        load = os.getloadavg()[0]
    except OSError:
        load = 0.0
    return {"instance": INSTANCE, "cores": os.cpu_count() or 1, "load": round(load, 2),
            "conv_active": sum(1 for c in conversions if c["status"] in CV_ACTIVE), "conv_paused": conv_state["paused"]}


def _http_json(url: str, body: dict | None = None, timeout: float = 4.0):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


async def peer_prober():
    peers = parse_peers(PEERS_RAW)
    while True:
        for name, url in peers.items():
            try:
                d = await asyncio.to_thread(_http_json, url + "/api/state")
                cap = d.get("capacity") or {}
                ok_ = isinstance(d.get("drives"), list) and isinstance(d.get("output"), dict)
                peers_state[name] = {"name": name, "url": url, "reachable": ok_, "instance": cap.get("instance", name),
                                     "cores": cap.get("cores", 0), "load": cap.get("load", 0), "conv_active": cap.get("conv_active", 0),
                                     "conv_paused": cap.get("conv_paused", False), "has_handover": bool(cap)}
            except Exception:  # noqa: BLE001
                old = peers_state.get(name, {})
                peers_state[name] = {**old, "name": name, "url": url, "reachable": False}
        broadcast()
        await asyncio.sleep(10)


def work_pending() -> bool:
    """Läuft hier noch Arbeit (Rip, Konvertierung, Übertragung)? Wenn nicht, darf der Rechner heruntergefahren werden."""
    return (any(d.job for d in drives.values()) or any(c["status"] in CV_ACTIVE for c in conversions)
            or any(u["status"] in ACTIVE for u in uploads))


async def hand_to_peer_after_upload(item: dict, base: Path, dr):
    """Übergabe einer frisch ins NAS übertragenen Datei: der andere Rechner konvertiert sie als Bibliotheks-Auftrag."""
    t = item["then_convert"]
    try:
        rel = str(Path(item["dest"]).relative_to(base.resolve())) if item.get("dest") else item["name"]
        r = await asyncio.to_thread(_http_json, t["url"] + "/api/library/convert", {"paths": [rel], "convert": t["cfg"]}, 15.0)
        ok_ = rel in r.get("started", [])
        msg = f"Zur Konvertierung an {t['name']} übergeben: {rel}" if ok_ else f"{t['name']} hat {rel} nicht angenommen: {r.get('skipped')}"
        if dr:
            dr.add_log(msg, "ok" if ok_ else "error")
        if not ok_:
            item["error"] = msg
    except Exception as e:  # noqa: BLE001
        item["error"] = f"Übergabe an {t['name']} fehlgeschlagen: {e}"
        if dr:
            dr.add_log(item["error"] + " – die Datei liegt unverändert im Ziel (Bibliothek → konvertieren).", "error")


def skip_conversion(item: dict):
    item["status"] = "skipped"
    item["t"] = time.time()
    for proc in conv_procs.get(item["id"], []):
        if proc.returncode is None:
            proc.terminate()
            if conv_state["paused"]:
                _signal_all([proc], signal.SIGCONT)      # ein angehaltener Prozess nimmt SIGTERM erst nach SIGCONT an


class HandoverReq(BaseModel):
    target: str


@app.post("/api/handover")
async def api_handover(req: HandoverReq):
    peer = peers_state.get(req.target)
    if not peer or not peer.get("reachable"):
        raise HTTPException(409, f"{req.target} ist nicht erreichbar.")
    if not peer.get("has_handover"):
        raise HTTPException(409, f"{req.target} läuft noch mit einer älteren Version ohne Übergabe – dort zuerst aktualisieren.")
    if any(d.job for d in drives.values()):
        raise HTTPException(409, "Ein Rip, Backup oder eine Analyse läuft – das Laufwerk hängt an diesem Rechner. Erst abwarten oder abbrechen.")
    handed, errors = [], []
    for c in [c for c in conversions if c["status"] in CV_ACTIVE]:
        label = c["name"]
        if c.get("origin") == "library":
            # Der andere Rechner übernimmt die Sperre (gleicher Besitzer), ich gebe sie nur auf, ohne die Datei freizugeben.
            try:
                r = await asyncio.to_thread(_http_json, peer["url"] + "/api/library/convert",
                                            {"paths": [c["rel"]], "convert": c["cfg"], "takeover_from": INSTANCE}, 15.0)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{label}: {e}")
                continue
            if c["rel"] not in r.get("started", []):
                errors.append(f"{label}: {r.get('skipped')}")
                continue
            held_locks.discard(c["lock"])
            c["lock"] = ""
        else:
            c["handover"] = {"url": peer["url"], "name": req.target}     # Original geht erst ins NAS, dann zum anderen Rechner
        c["handed"] = req.target
        skip_conversion(c)
        handed.append(label)
    broadcast()
    return {"ok": not errors, "handed": handed, "errors": errors, "target": req.target}


def snapshot():
    return {
        "drives": [dr.public() for dr in sorted(drives.values(), key=lambda x: (0 if (x.job or x.disc) else 1 if x.status == "ready" else 2, x.dev))],
        "settings": settings,
        "output": {"dir": out_cache["dir"], "mounted": out_cache["mounted"], "preferred": str(OUT_PREFERRED),
                   "free": out_cache["free"], "stalled": out_cache["stalled"]},
        "uploads": [{k: u[k] for k in ("id", "name", "size", "copied", "status", "error", "t", "speed", "eta", "replace")} for u in uploads
                    if not (u["status"] == "done" and time.time() - u["t"] > 600)],
        "conversions": [{k: c[k] for k in ("id", "name", "size_in", "size_out", "status", "pct", "fps", "speed", "eta", "error", "cfg", "t", "started", "mode", "origin", "paused", "handed")}
                        for c in conversions if not (c["status"] in ("done", "skipped") and time.time() - c["t"] > 900)],
        "conv_paused": conv_state["paused"],
        "capacity": capacity(),
        "peers": sorted(peers_state.values(), key=lambda x: x["name"]),
        "idle": not work_pending(),
        "staging": {"dir": str(STAGING), "free": shutil.disk_usage(STAGING).free if STAGING.exists() else 0},
        "key": {"custom": bool(settings["key"].strip()), "beta": bool(beta["key"]), "fetched": beta["fetched"], "error": beta["error"]},
        "now": time.time(),
    }


def get_drive(n: str) -> Drive:
    dr = drives.get(f"/dev/{n}")
    if not dr:
        raise HTTPException(404, "Laufwerk nicht gefunden")
    return dr


@app.get("/api/state")
def api_state():
    return snapshot()


@app.get("/api/events")
async def api_events():
    q: asyncio.Queue = asyncio.Queue(maxsize=1)
    clients.add(q)

    async def gen():
        try:
            yield f"data: {json.dumps(await asyncio.to_thread(snapshot))}\n\n"
            while True:
                try:
                    await asyncio.wait_for(q.get(), timeout=10)
                except asyncio.TimeoutError:
                    pass
                await asyncio.sleep(0.15)
                yield f"data: {json.dumps(await asyncio.to_thread(snapshot))}\n\n"
        finally:
            clients.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/drives/{n}/scan")
async def api_scan(n: str):
    dr = get_drive(n)
    if dr.busy:
        raise HTTPException(409, "Laufwerk ist beschäftigt")
    if dr.status != "ready":
        raise HTTPException(409, "Keine Disc im Laufwerk")
    asyncio.create_task(do_scan(dr))
    return {"ok": True}


@app.post("/api/drives/{n}/rip")
async def api_rip(n: str, req: RipReq):
    dr = get_drive(n)
    if dr.busy:
        raise HTTPException(409, "Laufwerk ist beschäftigt")
    if not dr.disc:
        raise HTTPException(409, "Disc wurde noch nicht analysiert")
    if req.mode not in ("mkv", "backup"):
        raise HTTPException(400, "Unbekannter Modus")
    if req.mode == "mkv" and not req.titles:
        raise HTTPException(400, "Keine Titel gewählt")
    base, _ = out_dir()
    folder = safe_name(req.folder or dr.disc["name"] or dr.disc["volume"])
    dest = base / folder
    need = sum(t["bytes"] for t in dr.disc["titles"] if t["id"] in {x.id for x in req.titles}) if req.mode == "mkv" else 50 * 2**30
    if shutil.disk_usage(base).free < need * 1.02:
        raise HTTPException(507, f"Zu wenig Speicherplatz in {base}")
    biggest = max([t["bytes"] for t in dr.disc["titles"] if t["id"] in {x.id for x in req.titles}] or [0]) if req.mode == "mkv" else 55 * 2**30
    uploading = sum(max(0, u["size"] - u["copied"]) for u in uploads if u["status"] in ACTIVE)
    factor = 1.7 if (req.convert and req.convert.get('convert') and req.mode == 'mkv') else 1.05
    if staging_free() + uploading < biggest * factor:
        raise HTTPException(507, f"Zu wenig Platz im Zwischenspeicher {STAGING}")
    asyncio.create_task(do_rip(dr, req, dest))
    return {"ok": True, "dest": str(dest)}


@app.post("/api/drives/{n}/cancel")
async def api_cancel(n: str):
    dr = get_drive(n)
    if dr.proc:
        dr.cancel = True
        dr.proc.terminate()
        asyncio.get_running_loop().call_later(6, lambda: dr.proc and dr.proc.kill())
    return {"ok": True}


@app.post("/api/drives/{n}/eject")
async def api_eject(n: str):
    dr = get_drive(n)
    if dr.busy:
        raise HTTPException(409, "Laufwerk ist beschäftigt")
    try:
        await asyncio.to_thread(tray, dr.dev, CDROM_EJECT)
    except OSError as e:
        raise HTTPException(500, f"Auswerfen fehlgeschlagen: {e}")
    return {"ok": True}


@app.post("/api/drives/{n}/close")
async def api_close(n: str):
    dr = get_drive(n)
    if dr.busy:
        raise HTTPException(409, "Laufwerk ist beschäftigt")
    try:
        await asyncio.to_thread(tray, dr.dev, CDROM_CLOSE_TRAY)
    except OSError as e:
        raise HTTPException(500, f"Einziehen fehlgeschlagen: {e}")
    return {"ok": True}


class SettingsReq(BaseModel):
    minlength: int | None = None
    auto_scan: bool | None = None
    auto_eject: bool | None = None
    audio_langs: str | None = None
    sub_langs: str | None = None
    key: str | None = None
    presets: dict | None = None
    conv_parallel: int | None = None
    conv_segments: int | None = None


@app.post("/api/settings")
async def api_settings(req: SettingsReq):
    for k, v in req.model_dump(exclude_none=True).items():
        if k == "presets":
            for kind in PRESET_DEFAULTS:
                if isinstance(v.get(kind), dict):
                    settings["presets"][kind] = clean_convert({**settings["presets"][kind], **v[kind]})
            continue
        if k == "conv_parallel":
            v = max(1, min(int(v), 8))
        if k == "conv_segments":
            v = max(0, min(int(v), 12))
        if k == "minlength":
            v = max(0, min(int(v), 36000))
        settings[k] = v.strip() if isinstance(v, str) else v
    save_settings()
    ensure_conv_workers()
    broadcast()
    return settings


class PauseReq(BaseModel):
    paused: bool


@app.post("/api/conversions/pause")
async def api_conv_pause(req: PauseReq):
    set_conv_paused(req.paused)
    broadcast()
    return {"ok": True, "paused": conv_state["paused"]}


@app.post("/api/conversions/{cid}/skip")
async def api_conv_skip(cid: int):
    item = next((c for c in conversions if c["id"] == cid), None)
    if not item or item["status"] not in CV_ACTIVE:
        raise HTTPException(404, "Keine laufende oder wartende Konvertierung")
    skip_conversion(item)
    broadcast()
    return {"ok": True}


@app.post("/api/key/refresh")
async def api_key_refresh():
    ok = await asyncio.to_thread(fetch_beta_key_sync)
    broadcast()
    if not ok:
        raise HTTPException(502, beta["error"])
    return {"ok": True}


def inside_out(rel: str) -> Path:
    base, _ = out_dir()
    p = (base / rel).resolve()
    if p != base.resolve() and base.resolve() not in p.parents:
        raise HTTPException(400, "Ungültiger Pfad")
    return p


class LibReq(BaseModel):
    paths: list[str] = []
    convert: dict = {}
    takeover_from: str = ""          # Übergabe: Name der Instanz, die die Sperre gerade hält und abgibt


@app.get("/api/library")
async def api_library():
    base, items, locks = await asyncio.to_thread(scan_library)
    active = {c["rel"]: c for c in conversions if c.get("origin") == "library" and c["status"] in CV_ACTIVE}
    done = {u["name"] for u in uploads if u.get("replace") and u["status"] in ACTIVE}
    out = []
    for it in items:
        rel = it["path"]
        c = lib_cache.get(rel)
        fresh = c and c["size"] == it["size"] and c["mtime"] == it["mtime"]
        if fresh:
            info, state = c["info"], lib_state(c["info"])
        else:
            info, state = None, "probing" if rel.lower().endswith(".mkv") else "other"
            if rel.lower().endswith(".mkv") and rel not in lib_probing:
                lib_probing.add(rel)
                lib_probe_queue.put_nowait(rel)
        job = None
        if rel in active:
            job = {"status": active[rel]["status"], "pct": active[rel]["pct"]}
        elif rel in done:
            job = {"status": "replacing", "pct": 1.0}
        lk = locks.get(rel)
        locked = None
        if lk and str(lk[1]) not in held_locks and time.time() - lk[0] < LOCK_TTL:
            try:
                locked = json.loads(lk[1].read_text()).get("inst", "andere Instanz")
            except (OSError, ValueError):
                locked = "andere Instanz"
        out.append({**it, "state": state, "info": info, "job": job, "locked": locked,
                    "dev_err": (c or {}).get("err", "") if not fresh or not c.get("info") else ""})
    out.sort(key=lambda x: -x["mtime"])
    return {"dir": base, "files": out[:1500], "probing": len(lib_probing), "instance": INSTANCE}


@app.post("/api/library/convert")
async def api_library_convert(req: LibReq):
    cfg = clean_convert({**req.convert, "convert": True})
    base, _ = out_dir()
    started, skipped = [], []
    for rel in req.paths[:300]:
        p = inside_out(rel)
        if not p.is_file():
            skipped.append({"path": rel, "why": "nicht gefunden"})
            continue
        if any(c.get("origin") == "library" and c["rel"] == rel and c["status"] in CV_ACTIVE for c in conversions):
            skipped.append({"path": rel, "why": "bereits in der Warteschlange"})
            continue
        st = p.stat()
        c = lib_cache.get(rel)
        if c and c["size"] == st.st_size and c["mtime"] == st.st_mtime and c["info"]:
            info = c["info"]
        else:
            try:
                info = lib_info(await probe(p))
            except Exception as e:  # noqa: BLE001
                skipped.append({"path": rel, "why": f"nicht lesbar: {str(e)[:80]}"})
                continue
            lib_cache[rel] = {"size": st.st_size, "mtime": st.st_mtime, "info": info}
        state = lib_state(info)
        if state != "ok":
            skipped.append({"path": rel, "why": {"hevc": "ist bereits HEVC", "hdr": "HDR – wird nicht umkodiert"}.get(state, "Codec wird nicht unterstützt")})
            continue
        owner = acquire_lock(p, req.takeover_from)
        if owner:
            skipped.append({"path": rel, "why": f"wird gerade von „{owner}“ bearbeitet"})
            continue
        global _cv_seq
        _cv_seq += 1
        conversions.append({"id": _cv_seq, "name": rel, "folder": str(Path(rel).parent), "src": str(p), "size_in": st.st_size, "size_out": 0,
                            "status": "queued", "pct": 0.0, "fps": 0.0, "speed": 0.0, "eta": 0, "error": "", "cfg": cfg, "dev": "",
                            "t": time.time(), "started": 0, "mode": "", "origin": "library", "rel": rel, "lock": str(lock_path(p)), "paused": False, "handed": ""})
        convert_queue.put_nowait(conversions[-1])
        started.append(rel)
    save_libcache()
    broadcast()
    return {"started": started, "skipped": skipped}


class RenameReq(BaseModel):
    path: str
    name: str


def valid_name(name: str) -> str:
    """Neuer Datei-/Ordnername: nur ein Name (kein Pfad), nicht versteckt, keine Steuerzeichen."""
    n = name.strip()
    if not n or n in (".", "..") or "/" in n or "\\" in n or n.startswith(".") or len(n) > 200 or re.search(r"[\x00-\x1f]", n):
        raise HTTPException(400, "Ungültiger Name (kein Pfad, nicht leer, nicht mit Punkt beginnend, höchstens 200 Zeichen).")
    return n


def move_cache(old: str, new: str):
    for k in [k for k in lib_cache if k == old or k.startswith(old + "/")]:
        lib_cache[new + k[len(old):]] = lib_cache.pop(k)
    save_libcache()


def busy_reason(rel: str, is_dir: bool, abs_path: Path) -> str:
    """Warum etwas gerade nicht umbenannt werden darf ('' = darf)."""
    hit = (lambda r: r.startswith(rel + "/")) if is_dir else (lambda r: r == rel)
    if any(c.get("origin") == "library" and c["status"] in CV_ACTIVE and hit(c["rel"]) for c in conversions):
        return "wird gerade konvertiert"
    if any(u["status"] in ACTIVE and (hit(u["name"]) or (is_dir and u["name"].startswith(rel + "/"))) for u in uploads):
        return "wird gerade übertragen"
    if is_dir and any(d.job and str(d.job.get("dest", "")).startswith(str(abs_path)) for d in drives.values()):
        return "wird gerade von einem Rip beschrieben"
    return ""


def fresh_lock_in(p: Path, is_dir: bool) -> bool:
    paths = [p] if not is_dir else [f for f in p.rglob("*") if f.is_file() and f.name.endswith(".mkw-lock")]
    for f in paths:
        lp = f if is_dir else lock_path(p)
        try:
            if time.time() - lp.stat().st_mtime < LOCK_TTL and str(lp) not in held_locks:
                return True
        except OSError:
            continue
    return False


@app.post("/api/library/rename")
async def api_lib_rename(req: RenameReq):
    src = inside_out(req.path)
    if not src.is_file():
        raise HTTPException(404, "Datei nicht gefunden")
    name = valid_name(req.name)
    if Path(name).suffix.lower() != src.suffix.lower():
        name += src.suffix                                   # Endung bleibt erhalten
    dst = src.with_name(name)
    base = Path(out_cache["dir"]).resolve()
    rel_old, rel_new = str(src.relative_to(base)), str(dst.relative_to(base))
    if dst == src:
        return {"ok": True, "path": rel_old}
    if why := busy_reason(rel_old, False, src):
        raise HTTPException(409, f"Die Datei {why} und kann jetzt nicht umbenannt werden.")
    if fresh_lock_in(src, False):
        raise HTTPException(409, "Die Datei ist von einer anderen Instanz gesperrt.")
    if dst.exists():
        raise HTTPException(409, f"„{name}“ gibt es in diesem Ordner schon.")
    try:
        os.rename(src, dst)
    except PermissionError:
        raise HTTPException(403, "Keine Berechtigung zum Umbenennen (Ordner gehört auf dem NAS einem anderen Benutzer).")
    except OSError as e:
        raise HTTPException(500, f"Umbenennen fehlgeschlagen: {e}")
    move_cache(rel_old, rel_new)
    broadcast()
    return {"ok": True, "path": rel_new}


@app.post("/api/library/rename-folder")
async def api_lib_rename_folder(req: RenameReq):
    src = inside_out(req.path)
    base = Path(out_cache["dir"]).resolve()
    if not src.is_dir() or src == base:
        raise HTTPException(404, "Ordner nicht gefunden")
    name = valid_name(req.name)
    dst = src.with_name(name)
    rel_old, rel_new = str(src.relative_to(base)), str(dst.relative_to(base))
    if dst == src:
        return {"ok": True, "path": rel_old}
    if why := busy_reason(rel_old, True, src):
        raise HTTPException(409, f"Im Ordner {why}; er kann jetzt nicht umbenannt werden.")
    if fresh_lock_in(src, True):
        raise HTTPException(409, "Im Ordner ist eine Datei von einer anderen Instanz gesperrt.")
    if dst.exists():
        raise HTTPException(409, f"„{name}“ gibt es hier schon.")
    try:
        os.rename(src, dst)
    except PermissionError:
        raise HTTPException(403, "Keine Berechtigung zum Umbenennen (gehört auf dem NAS einem anderen Benutzer).")
    except OSError as e:
        raise HTTPException(500, f"Umbenennen fehlgeschlagen: {e}")
    move_cache(rel_old, rel_new)
    broadcast()
    return {"ok": True, "path": rel_new}


@app.get("/api/files")
def api_files():
    base, _ = out_dir()
    items = []
    for root, dirs, files in os.walk(base):
        depth = Path(root).relative_to(base).parts
        if len(depth) >= 3:
            dirs[:] = []
        for f in files:
            if f.lower().endswith((".mkv", ".iso", ".m2ts")):
                p = Path(root) / f
                try:
                    st = p.stat()
                except OSError:
                    continue
                items.append({"path": str(p.relative_to(base)), "size": st.st_size, "mtime": st.st_mtime})
    items.sort(key=lambda x: -x["mtime"])
    return {"dir": str(base), "files": items[:200]}


@app.get("/api/download")
def api_download(path: str):
    p = inside_out(path)
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, filename=p.name)


@app.delete("/api/files")
def api_delete(path: str):
    p = inside_out(path)
    if not p.is_file():
        raise HTTPException(404)
    lp = lock_path(p)
    if lp.exists() and time.time() - lp.stat().st_mtime < LOCK_TTL:
        raise HTTPException(409, "Die Datei wird gerade konvertiert und kann jetzt nicht gelöscht werden.")
    try:
        p.unlink()
    except PermissionError:
        raise HTTPException(403, "Keine Berechtigung zum Löschen: Datei oder Ordner gehört auf dem NAS einem anderen Benutzer. "
                                 "Auf dem NAS die Rechte öffnen (chmod a+rwX) oder die Datei dort löschen.")
    except OSError as e:
        raise HTTPException(500, f"Löschen fehlgeschlagen: {e}")
    parent = p.parent
    base, _ = out_dir()
    if parent.resolve() != base.resolve():
        try:
            parent.rmdir()
        except OSError:
            pass
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "index.html", headers={"Cache-Control": "no-cache"})
