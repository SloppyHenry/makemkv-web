"""Tests für den Player (Paket PD).

Braucht Python >= 3.10 mit fastapi (wie die App; bei Bedarf PYTHON=/opt/homebrew/bin/python3).
Reine Logik (Entscheidung Direkt/Remux/Transkodieren, Pfadprüfung):   python3 -m unittest tests.test_player
Mit laufender Dev-Instanz zusätzlich HTTP-Tests (Strom, Suchen, Aufräumen, Pfadausbruch, Sperre):
    PLAYER_URL=http://127.0.0.1:8830 PLAYER_OUT=$TMPDIR/mkw-dev-d/output python3 -m unittest tests.test_player
Die HTTP-Tests legen im Ausgabeordner nur eigene Hilfsdateien an (`_pdtest*`) und räumen sie wieder auf. Nie gegen das echte NAS laufen lassen.
"""
import json
import os
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="pdtest-")
os.environ.setdefault("DATA_DIR", _tmp + "/data")
os.environ.setdefault("OUTPUT_DIR", _tmp + "/out")
os.environ.setdefault("FALLBACK_DIR", _tmp + "/out")
os.environ.setdefault("OUTPUT_MOUNT", _tmp + "/kein-mount")

from fastapi import HTTPException  # noqa: E402
from app import player_probe as pp  # noqa: E402

CAPS_CHROME = pp.parse_caps("mkv,h264,h264_10,hevc,hevc10,vp9,av1,aac,opus,flac")
CAPS_SAFARI = pp.parse_caps("h264,hevc,hevc10,aac,ac3,eac3")


def info(vcodec="h264", bits=8, audio=(("aac", 2),), subs=(), hdr=False, interlaced=False):
    return {"duration": 100.0, "container": "matroska,webm", "size": 1, "bitrate": 1, "chapters": [],
            "video": {"codec": vcodec, "profile": "", "pix_fmt": "yuv420p", "w": 1920, "h": 1080, "bits": bits, "fps": 24.0, "hdr": hdr, "interlaced": interlaced, "stream": 0},
            "audio": [{"i": i, "stream": i + 1, "codec": c, "profile": "", "channels": ch, "layout": "", "lang": "", "title": "", "default": i == 0} for i, (c, ch) in enumerate(audio)],
            "subs": [{"i": i, "stream": 9 + i, "codec": c, "lang": "", "title": "", "forced": False, "default": False,
                      "kind": "text" if c in pp.TEXT_SUBS else "bitmap"} for i, c in enumerate(subs)]}


class PlanTests(unittest.TestCase):
    def test_direct_mp4_h264_aac(self):
        p = pp.plan(info(), CAPS_CHROME, ext=".mp4")
        self.assertEqual((p["mode"], p["video"], p["audio"]), ("direct", "copy", "copy"))

    def test_mkv_direct_nur_wenn_browser_mkv_kann(self):
        self.assertEqual(pp.plan(info(), CAPS_CHROME, ext=".mkv")["mode"], "direct")
        self.assertEqual(pp.plan(info(), CAPS_SAFARI, ext=".mkv")["mode"], "remux")

    def test_ac3_wird_remux_mit_aac(self):
        p = pp.plan(info(audio=(("ac3", 6),)), CAPS_CHROME, ext=".mkv")
        self.assertEqual((p["mode"], p["video"], p["audio"]), ("remux", "copy", "aac"))
        self.assertTrue(any("AAC" in r for r in p["reasons"]))

    def test_ac3_bleibt_in_safari(self):
        p = pp.plan(info(audio=(("ac3", 6),)), CAPS_SAFARI, ext=".mkv")
        self.assertEqual((p["mode"], p["audio"]), ("remux", "copy"))

    def test_andere_tonspur_geht_nie_direkt(self):
        p = pp.plan(info(audio=(("aac", 2), ("aac", 2))), CAPS_CHROME, audio=1, ext=".mp4")
        self.assertEqual((p["mode"], p["audio"]), ("remux", "copy"))

    def test_mpeg2_und_vc1_werden_transkodiert(self):
        for c in ("mpeg2video", "vc1"):
            p = pp.plan(info(vcodec=c, audio=(("ac3", 6),)), CAPS_CHROME, ext=".mkv")
            self.assertEqual((p["mode"], p["video"]), ("transcode", "x264"), c)

    def test_hevc10_je_nach_browser(self):
        self.assertEqual(pp.plan(info("hevc", 10), CAPS_CHROME, ext=".mkv")["mode"], "direct")
        self.assertEqual(pp.plan(info("hevc", 10), pp.parse_caps("h264,aac"), ext=".mkv")["video"], "x264")

    def test_erzwingen(self):
        self.assertEqual(pp.plan(info(), CAPS_CHROME, force="transcode", ext=".mp4")["mode"], "transcode")
        self.assertEqual(pp.plan(info(), CAPS_CHROME, force="remux", ext=".mp4")["mode"], "remux")

    def test_bilduntertitel_einbrennen_erzwingt_transkodierung(self):
        i = info(subs=("hdmv_pgs_subtitle", "subrip"))
        self.assertEqual(pp.plan(i, CAPS_CHROME, burn=0, ext=".mkv")["burn"], 0)
        self.assertEqual(pp.plan(i, CAPS_CHROME, burn=0, ext=".mkv")["mode"], "transcode")
        self.assertIsNone(pp.plan(i, CAPS_CHROME, burn=1, ext=".mkv")["burn"])          # Textspur lässt sich nicht einbrennen
        self.assertEqual(pp.plan(i, CAPS_CHROME, ext=".mkv")["mode"], "direct")

    def test_transkodieren_ausgeschaltet(self):
        p = pp.plan(info("mpeg2video"), CAPS_CHROME, transcode_allowed=False, ext=".mkv")
        self.assertFalse(p["ok"])
        self.assertTrue(pp.plan(info(), CAPS_CHROME, transcode_allowed=False, ext=".mp4")["ok"])

    def test_ohne_video(self):
        i = info()
        i["video"] = None
        self.assertFalse(pp.plan(i, CAPS_CHROME)["ok"])

    def test_ohne_ton(self):
        p = pp.plan(info(audio=()), CAPS_CHROME, ext=".mp4")
        self.assertEqual((p["mode"], p["audio"]), ("direct", "none"))


class SweepTests(unittest.IsolatedAsyncioTestCase):
    """Wächter: Ein Prozess, aus dem niemand mehr Daten abholt, wird beendet; nie abgeholte Sitzungen verfallen."""

    async def test_leerlauf_und_nie_abgeholt(self):
        import asyncio
        import time
        from app import player_stream as ps
        pr = await asyncio.create_subprocess_exec("sleep", "60", start_new_session=True)
        ps.sessions["a"] = {"id": "a", "client": "x", "proc": pr, "created": time.time(), "last_io": time.time() - ps.IDLE_KILL - 1, "plan": {"video": "copy"}}
        ps.sessions["b"] = {"id": "b", "client": "y", "proc": None, "created": time.time() - ps.NEVER_FETCHED - 1, "last_io": 0, "plan": {"video": "x264"}}
        ps.sessions["c"] = {"id": "c", "client": "z", "proc": None, "created": time.time(), "last_io": 0, "plan": {"video": "x264"}}
        await ps.sweep()
        self.assertEqual(sorted(ps.sessions), ["c"])
        self.assertIsNotNone(pr.returncode if pr.returncode is not None else await asyncio.wait_for(pr.wait(), 3))
        ps.sessions.clear()


class PathTests(unittest.TestCase):
    def setUp(self):
        from app.files import out_dir
        self.base = out_dir()[0]
        (self.base / "a").mkdir(parents=True, exist_ok=True)
        (self.base / "a" / "f.mkv").write_bytes(b"x")
        (self.base / "a" / "d.iso").write_bytes(b"x")
        (self.base / "a" / ".f.mkv.mkw-lock").write_bytes(b"{}")
        (self.base / "a" / "t.txt").write_bytes(b"x")
        outside = Path(_tmp) / "draussen.mkv"
        outside.write_bytes(b"x")
        link = self.base / "a" / "link.mkv"
        if not link.is_symlink():
            link.symlink_to(outside)

    def code(self, rel):
        try:
            pp.check_path(rel)
            return 200
        except HTTPException as e:
            return e.status_code

    def test_pfade(self):
        self.assertEqual(self.code("a/f.mkv"), 200)
        for bad in ("../x.mkv", "../../etc/passwd", "/etc/passwd", "a/../../x.mkv", "", "a/f.mkv\x00.txt", "a/.f.mkv.mkw-lock", ".versteckt.mkv", "a/link.mkv"):
            self.assertEqual(self.code(bad), 400 if bad != "" else 400, bad)
        self.assertEqual(self.code("a/d.iso"), 415)
        self.assertEqual(self.code("a/t.txt"), 415)
        self.assertEqual(self.code("a/gibtsnicht.mkv"), 404)
        self.assertEqual(self.code("a"), 415)


# ----------------------------------------------------------------- HTTP gegen eine laufende Dev-Instanz
URL, OUT = os.environ.get("PLAYER_URL", ""), os.environ.get("PLAYER_OUT", "")
FILM = "Beispielfilm (2019)/Beispielfilm (2019).mkv"
DVD = "Beispiel DVD (2005)/Beispiel DVD (2005).mkv"


def call(path, body=None, method=None, timeout=60, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL + path, data=data, method=method or ("POST" if body is not None else "GET"), headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def session(path, **kw):
    s, b, _ = call("/api/player/session", {"path": path, "caps": "h264,aac", **kw})
    return s, (json.loads(b) if b else {})


def running_pids():
    """PIDs der ffmpeg-Prozesse dieser Dev-Instanz (nur eigene, andere Agenten dürfen gleichzeitig ffmpeg nutzen)."""
    return [x["pid"] for x in json.loads(call("/api/player/sessions")[1]) if x["running"]]


def alive(pid):
    try:
        os.kill(pid, 0)
        import subprocess
        return "Z" not in subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout
    except OSError:
        return False


@unittest.skipUnless(URL, "PLAYER_URL nicht gesetzt (keine Dev-Instanz)")
class HttpTests(unittest.TestCase):
    def test_probe_und_sitzung_remux(self):
        s, b, _ = call("/api/player/probe?path=" + urllib.parse.quote(FILM) + "&caps=h264,aac")
        d = json.loads(b)
        self.assertEqual((s, d["plan"]["mode"], len(d["chapters"]), d["subs"][0]["kind"]), (200, "remux", 3, "text"))
        s, d = session(FILM, client="pdt1")
        self.assertEqual(s, 200)
        s, body, h = call(d["url"])
        self.assertEqual((s, h["Content-Type"]), (200, "video/mp4"))
        self.assertGreater(len(body), 100000)
        self.assertEqual(body[4:8], b"ftyp")

    def test_suchen_startet_am_keyframe(self):
        s, d = session(FILM, client="pdt2", start=61.5)
        self.assertEqual(s, 200)
        self.assertAlmostEqual(d["start"], 52.083, places=2)

    def test_direkt_range(self):
        s, d = session("Beispiel HEVC 10-bit (2021)/Beispiel HEVC 10-bit (2021).mkv", client="pdt3", caps="mkv,h264,hevc,hevc10,aac")
        self.assertEqual((s, d["mode"], d["native_seek"]), (200, "direct", True))
        s, b, h = call(d["url"], headers={"Range": "bytes=10-19"})
        self.assertEqual((s, len(b), h["Content-Range"].startswith("bytes 10-19/")), (206, 10, True))

    def test_pfadausbruch(self):
        for bad in ("../etc/passwd", "/etc/passwd", "a/../../x.mkv", ".x.mkv"):
            for ep in ("probe", "file", "subtitle"):
                s, _, _ = call(f"/api/player/{ep}?path=" + urllib.parse.quote(bad) + "&index=0")
                self.assertEqual(s, 400, (ep, bad))
            s, _ = session(bad)
            self.assertEqual(s, 400, bad)

    def test_untertitel_webvtt(self):
        s, b, h = call("/api/player/subtitle?path=" + urllib.parse.quote(FILM) + "&index=0")
        self.assertEqual(s, 200)
        self.assertTrue(b.decode().startswith("WEBVTT"))
        self.assertIn("äöü", b.decode())
        self.assertEqual(call("/api/player/subtitle?path=" + urllib.parse.quote(FILM) + "&index=7")[0], 404)

    def test_nur_eine_transkodierung_und_aufraeumen(self):
        import subprocess
        s, d1 = session(DVD, client="pdtA")
        self.assertEqual((s, d1["mode"]), (200, "transcode"))
        s, d2 = session(DVD, client="pdtB")                       # anderer Browser, erster Strom noch nicht abgeholt: reserviert
        self.assertEqual(s, 409)
        s, d3 = session(DVD, client="pdtA", start=5)               # derselbe Browser ersetzt seinen Strom
        self.assertEqual(s, 200)
        # Strom abholen und nach 2 s Verbindung kappen: ffmpeg muss verschwinden
        p = subprocess.Popen(["curl", "-s", "-o", "/dev/null", "--limit-rate", "20k", URL + d3["url"]])
        time.sleep(3)
        pids = running_pids()
        self.assertEqual(len(pids), 1)
        p.kill()
        time.sleep(3)
        self.assertFalse(alive(pids[0]), "ffmpeg lief nach dem Verbindungsabriss weiter")
        s, _ = session(DVD, client="pdtB")                          # jetzt frei
        self.assertEqual(s, 200)
        call("/api/player/stop", {"client": "pdtB"})

    def test_stop_beendet_strom(self):
        import subprocess
        s, d = session(DVD, client="pdtS")
        p = subprocess.Popen(["curl", "-s", "-o", "/dev/null", "--limit-rate", "20k", URL + d["url"]])
        time.sleep(3)
        pids = running_pids()
        self.assertEqual(len(pids), 1)
        call("/api/player/stop", {"client": "pdtS"})
        time.sleep(3)
        self.assertFalse(alive(pids[0]))
        p.kill()

    @unittest.skipUnless(OUT, "PLAYER_OUT nicht gesetzt")
    def test_gesperrte_datei_bleibt_abspielbar(self):
        src = Path(OUT) / FILM
        lock = src.with_name("." + src.name + ".mkw-lock")
        lock.write_text(json.dumps({"inst": "maintux", "t": time.time()}))
        try:
            s, b, _ = call("/api/player/probe?path=" + urllib.parse.quote(FILM) + "&caps=h264,aac")
            d = json.loads(b)
            self.assertEqual(s, 200)
            self.assertEqual(d["locked"]["by"], "maintux")
            self.assertEqual(call("/api/player/file?path=" + urllib.parse.quote(FILM), headers={"Range": "bytes=0-9"})[0], 206)
        finally:
            lock.unlink(missing_ok=True)

    @unittest.skipUnless(OUT, "PLAYER_OUT nicht gesetzt")
    def test_symlink_nach_draussen(self):
        link = Path(OUT) / "_pdtest_link.mkv"
        link.unlink(missing_ok=True)
        link.symlink_to("/etc/hosts")
        try:
            for ep in ("probe", "file"):
                self.assertEqual(call(f"/api/player/{ep}?path=_pdtest_link.mkv")[0], 400)
        finally:
            link.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
