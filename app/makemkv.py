"""makemkvcon: Konfiguration, Beta-Key und Auswertung des Robot-Modus."""
import asyncio
import json
import os
import re
import time
import urllib.request

from fastapi import APIRouter, HTTPException
from app.config import BETAKEY, DATA, FORUM_URL, MKV_DIR
from app.state import beta, broadcast, settings
from app.util import hms_to_sec


router = APIRouter()


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


MSG_RE = re.compile(r'^MSG:(\d+),(\d+),(\d+),"(.*?)",".*$')
INFO_RE = {
    "C": re.compile(r'^CINFO:(\d+),(\d+),"(.*)"$'),
    "T": re.compile(r'^TINFO:(\d+),(\d+),(\d+),"(.*)"$'),
    "S": re.compile(r'^SINFO:(\d+),(\d+),(\d+),(\d+),"(.*)"$'),
}


class Parser:
    """Liest den makemkvcon-Robot-Modus."""

    def __init__(self, drive, job: dict):
        self.d, self.job = drive, job
        self.cinfo, self.tinfo, self.sinfo = {}, {}, {}
        self.saved = None
        self.disc_index = None
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
            m = re.match(r'^DRV:(\d+),\d+,\d+,\d+,"[^"]*","([^"]*)","([^"]*)"$', line)
            if m and m.group(3) == d.dev:
                self.disc_index = int(m.group(1))
                if m.group(2):
                    d.label = m.group(2)
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
        elif line.strip() and not line.startswith(("MSG:", "DRV:", "PRG", "TCOUNT:", "CINFO:", "TINFO:", "SINFO:")):   # Klartext-Fehler von makemkvcon
            self.errors.append(line.strip())
            d.add_log(line.strip(), "error")

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


async def run_makemkv(drive, args: list[str], parser: Parser) -> int:
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


async def key_refresher():
    while True:
        if not settings["key"].strip() and (not beta["key"] or time.time() - beta["fetched"] > 12 * 3600):
            await asyncio.to_thread(fetch_beta_key_sync)
            broadcast()
        await asyncio.sleep(1800)


@router.post("/api/key/refresh")
async def api_key_refresh():
    ok = await asyncio.to_thread(fetch_beta_key_sync)
    broadcast()
    if not ok:
        raise HTTPException(502, beta["error"])
    return {"ok": True}
