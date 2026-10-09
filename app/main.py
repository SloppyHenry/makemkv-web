"""MakeMKV-Web: headless MakeMKV mit Browser-Oberfläche.

- erkennt Laufwerke (/dev/sr*) und eingelegte Discs live (ioctl, kein Eingriff in laufende Jobs)
- analysiert neu eingelegte Discs automatisch (makemkvcon info)
- rippt gewählte Titel als MKV oder macht ein entschlüsseltes Disc-Backup
- Ausgabe nach /mnt/nas/rips, solange eingehängt (sonst lokaler Fallback)
"""
import asyncio
import base64
import copy
import secrets
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
MKV_DIR = DATA / ".MakeMKV"
CONFIG = DATA / "config.json"
BETAKEY = DATA / "betakey.json"
FORUM_URL = "https://forum.makemkv.com/forum/viewtopic.php?f=5&t=1053"

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
    if c.get("tune") in ("none", "grain", "film", "animation"):
        d["tune"] = c["tune"]
    extra = str(c.get("extra", d["extra"])).strip()
    d["extra"] = extra if re.fullmatch(r"[A-Za-z0-9_=:.,\-]*", extra) else CONVERT_DEFAULT["extra"]
    if c.get("audio") in ("copy", "ac3", "eac3", "opus"):
        d["audio"] = c["audio"]
    return d


def load_settings():
    try:
        settings.update({k: v for k, v in json.loads(CONFIG.read_text()).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
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


def enqueue_upload(src: Path, rel: str, dev: str = ""):
    global _up_seq
    _up_seq += 1
    item = {"id": _up_seq, "name": rel, "src": str(src), "size": tree_size(src), "copied": 0,
            "status": "queued", "error": "", "dev": dev, "t": time.time()}
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
    mkdir_open(target.parent, base)
    if src.is_file():
        target = unique_path(target)
        if os.stat(src).st_dev == os.stat(target.parent).st_dev:      # gleiches Dateisystem: nur umbenennen
            os.replace(src, target)
            open_perms(target, False)
            item.update(copied=item["size"], dest=str(target))
            return
        files = [(src, target)]
    else:
        files = [(f, target / f.relative_to(src)) for f in sorted(src.rglob("*")) if f.is_file()]
    item["size"], item["copied"] = sum(a.stat().st_size for a, _ in files), 0
    last = 0.0
    for a, b in files:
        mkdir_open(b.parent, base)
        part = b.with_name(b.name + ".part")
        with open(a, "rb") as fi, open(part, "wb") as fo:
            while chunk := fi.read(8 * 2**20):
                fo.write(chunk)
                item["copied"] += len(chunk)
                if time.monotonic() - last > 0.5:
                    last = time.monotonic()
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
                item.update(status="done", t=time.time())
                if dr:
                    dr.add_log(f"Übertragen: {item['name']} ({fmt_bytes(item['size'])})", "ok")
                break
            except Exception as e:  # noqa: BLE001
                item.update(status="retry" if attempt < 5 else "error", error=str(e))
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
conv_procs: dict[int, asyncio.subprocess.Process] = {}
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
                        "cfg": cfg, "dev": dev, "t": time.time(), "started": 0})
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


def ffmpeg_args(src: Path, out: Path, cfg: dict, info: dict, crop) -> list[str]:
    a = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src), "-map", "0:v:0", "-map", "0:a?", "-map", "0:s?", "-map_chapters", "0"]
    if crop:
        a += ["-vf", crop]
    a += ["-c:v", "libx265", "-preset", cfg["preset"], "-crf", str(cfg["rf"]), "-pix_fmt", "yuv420p10le", "-fps_mode", "cfr"]
    if cfg["tune"] != "none":
        a += ["-tune", cfg["tune"]]
    a += ["-x265-params", "log-level=error" + (":" + cfg["extra"] if cfg["extra"] else "")]
    auds = [x for x in info["streams"] if x["codec_type"] == "audio"]
    if cfg["audio"] == "copy" or not auds:
        a += ["-c:a", "copy"]
    else:
        for i, st in enumerate(auds):
            ch = int(st.get("channels") or 2)
            if cfg["audio"] == "opus":
                layout = {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}.get(ch)
                a += [f"-c:a:{i}", "libopus", f"-b:a:{i}", "128k" if ch <= 2 else "320k" if ch <= 6 else "448k"]
                if layout:
                    a += [f"-filter:a:{i}", f"aformat=channel_layouts={layout}"]
            else:
                if ch > 6:
                    a += [f"-ac:a:{i}", "6"]
                a += [f"-c:a:{i}", cfg["audio"], f"-b:a:{i}", "192k" if ch <= 2 else "640k"]
    a += ["-c:s", "copy", "-progress", "pipe:1", "-nostats", str(out)]
    return a


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
    CONV_WORK.mkdir(parents=True, exist_ok=True)
    out = CONV_WORK / f"{item['id']}.mkv"
    proc = await asyncio.create_subprocess_exec("nice", "-n", "10", *ffmpeg_args(src, out, cfg, info, crop),
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=2**20)
    conv_procs[item["id"]] = proc
    tail: deque = deque(maxlen=12)

    async def read_err():
        async for raw in proc.stderr:
            tail.append(raw.decode(errors="replace").strip())

    err_task = asyncio.create_task(read_err())
    last = 0.0
    try:
        async for raw in proc.stdout:
            k, _, val = raw.decode(errors="replace").strip().partition("=")
            if k == "out_time_us" and val.lstrip("-").isdigit():
                t = int(val) / 1e6
                item["pct"] = max(0.0, min(0.99, t / dur))
                if item["speed"] > 0:
                    item["eta"] = max(0, (dur - t) / item["speed"])
            elif k == "fps":
                item["fps"] = float(val or 0)
            elif k == "speed":
                try:
                    item["speed"] = float(val.rstrip("x") or 0)
                except ValueError:
                    pass
            elif k == "total_size" and val.isdigit():
                item["size_out"] = int(val)
            if time.monotonic() - last > 0.7:
                last = time.monotonic()
                broadcast()
        rc = await proc.wait()
    finally:
        conv_procs.pop(item["id"], None)
        await err_task
    if item["status"] == "skipped":
        out.unlink(missing_ok=True)
        raise SkipConversion()
    if rc != 0 or not out.exists():
        out.unlink(missing_ok=True)
        raise OSError("ffmpeg fehlgeschlagen: " + " | ".join(list(tail)[-4:]))
    od = float((await probe(out))["format"]["duration"])
    if abs(od - dur) > max(2.0, dur * 0.01):
        out.unlink(missing_ok=True)
        raise OSError(f"Ergebnis hat falsche Länge ({od:.0f}s statt {dur:.0f}s)")
    return out


def release_original(item: dict):
    """Original unverändert in die Übertragung geben (Konvertierung übersprungen/fehlgeschlagen) – nichts geht verloren."""
    src = Path(item["src"])
    if src.exists():
        rdir = READY / item["folder"]
        rdir.mkdir(parents=True, exist_ok=True)
        final = unique_path(rdir / src.name)
        os.replace(src, final)
        enqueue_upload(final, f"{item['folder']}/{final.name}", item["dev"])
    src.with_name(src.name + ".json").unlink(missing_ok=True)
    try:
        src.parent.rmdir()
    except OSError:
        pass


async def convert_worker():
    while True:
        item = await convert_queue.get()
        dr = drives.get(item["dev"])
        if item["status"] != "skipped":
            for attempt in (1, 2):
                try:
                    out = await convert_one(item)
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


def snapshot():
    return {
        "drives": [dr.public() for dr in sorted(drives.values(), key=lambda x: (0 if (x.job or x.disc) else 1 if x.status == "ready" else 2, x.dev))],
        "settings": settings,
        "output": {"dir": out_cache["dir"], "mounted": out_cache["mounted"], "preferred": str(OUT_PREFERRED),
                   "free": out_cache["free"], "stalled": out_cache["stalled"]},
        "uploads": [{k: u[k] for k in ("id", "name", "size", "copied", "status", "error", "t")} for u in uploads
                    if not (u["status"] == "done" and time.time() - u["t"] > 600)],
        "conversions": [{k: c[k] for k in ("id", "name", "size_in", "size_out", "status", "pct", "fps", "speed", "eta", "error", "cfg", "t", "started")}
                        for c in conversions if not (c["status"] in ("done", "skipped") and time.time() - c["t"] > 900)],
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


@app.post("/api/settings")
async def api_settings(req: SettingsReq):
    for k, v in req.model_dump(exclude_none=True).items():
        if k == "presets":
            for kind in PRESET_DEFAULTS:
                if isinstance(v.get(kind), dict):
                    settings["presets"][kind] = clean_convert({**settings["presets"][kind], **v[kind]})
            continue
        if k == "minlength":
            v = max(0, min(int(v), 36000))
        settings[k] = v.strip() if isinstance(v, str) else v
    save_settings()
    broadcast()
    return settings


@app.post("/api/conversions/{cid}/skip")
async def api_conv_skip(cid: int):
    item = next((c for c in conversions if c["id"] == cid), None)
    if not item or item["status"] not in CV_ACTIVE:
        raise HTTPException(404, "Keine laufende oder wartende Konvertierung")
    item["status"] = "skipped"
    item["t"] = time.time()
    proc = conv_procs.get(cid)
    if proc:
        proc.terminate()
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
