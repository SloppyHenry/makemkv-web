"""Tests for the player (package PD).

Needs Python >= 3.10 with fastapi (like the app; if necessary PYTHON=/opt/homebrew/bin/python3).
Pure logic (decision direct/remux/transcode, path checks):   python3 -m unittest tests.test_player
With a running dev instance additionally HTTP tests (stream, seeking, cleanup, path escape, lock):
    PLAYER_URL=http://127.0.0.1:8830 PLAYER_OUT=$TMPDIR/mkw-dev-d/output python3 -m unittest tests.test_player
The HTTP tests only create their own helper files in the output folder (`_pdtest*`) and clean them up again. Never run them against the real NAS.
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
os.environ.setdefault("OUTPUT_MOUNT", _tmp + "/no-mount")

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

    def test_mkv_direct_only_if_browser_supports_mkv(self):
        self.assertEqual(pp.plan(info(), CAPS_CHROME, ext=".mkv")["mode"], "direct")
        self.assertEqual(pp.plan(info(), CAPS_SAFARI, ext=".mkv")["mode"], "remux")

    def test_ac3_becomes_remux_with_aac(self):
        p = pp.plan(info(audio=(("ac3", 6),)), CAPS_CHROME, ext=".mkv")
        self.assertEqual((p["mode"], p["video"], p["audio"]), ("remux", "copy", "aac"))
        self.assertTrue(any("AAC" in r for r in p["reasons"]))

    def test_ac3_stays_in_safari(self):
        p = pp.plan(info(audio=(("ac3", 6),)), CAPS_SAFARI, ext=".mkv")
        self.assertEqual((p["mode"], p["audio"]), ("remux", "copy"))

    def test_other_audio_track_never_direct(self):
        p = pp.plan(info(audio=(("aac", 2), ("aac", 2))), CAPS_CHROME, audio=1, ext=".mp4")
        self.assertEqual((p["mode"], p["audio"]), ("remux", "copy"))

    def test_mpeg2_and_vc1_are_transcoded(self):
        for c in ("mpeg2video", "vc1"):
            p = pp.plan(info(vcodec=c, audio=(("ac3", 6),)), CAPS_CHROME, ext=".mkv")
            self.assertEqual((p["mode"], p["video"]), ("transcode", "x264"), c)

    def test_hevc10_depending_on_browser(self):
        self.assertEqual(pp.plan(info("hevc", 10), CAPS_CHROME, ext=".mkv")["mode"], "direct")
        self.assertEqual(pp.plan(info("hevc", 10), pp.parse_caps("h264,aac"), ext=".mkv")["video"], "x264")

    def test_force_remux(self):
        self.assertEqual(pp.plan(info(), CAPS_CHROME, force="remux", ext=".mp4")["mode"], "remux")

    def test_never_transcode_if_browser_can_play(self):
        """If the browser can play the video, it is never transcoded (not even with image subtitle tracks)."""
        p = pp.plan(info(subs=("hdmv_pgs_subtitle", "subrip")), CAPS_CHROME, ext=".mkv")
        self.assertEqual((p["mode"], p["video"]), ("direct", "copy"))
        self.assertNotIn("burn", p)

    def test_preferred_audio_track_direct_others_remux(self):
        i = info(audio=(("aac", 2), ("aac", 2)))
        self.assertEqual(pp.plan(i, CAPS_CHROME, ext=".mp4", pref_audio=1)["mode"], "direct")        # the language setting chooses track 1
        self.assertEqual(pp.plan(i, CAPS_CHROME, audio=0, ext=".mp4", pref_audio=1)["mode"], "remux")

    def test_transcoding_switched_off(self):
        p = pp.plan(info("mpeg2video"), CAPS_CHROME, transcode_allowed=False, ext=".mkv")
        self.assertFalse(p["ok"])
        self.assertTrue(pp.plan(info(), CAPS_CHROME, transcode_allowed=False, ext=".mp4")["ok"])

    def test_without_video(self):
        i = info()
        i["video"] = None
        self.assertFalse(pp.plan(i, CAPS_CHROME)["ok"])

    def test_without_audio(self):
        p = pp.plan(info(audio=()), CAPS_CHROME, ext=".mp4")
        self.assertEqual((p["mode"], p["audio"]), ("direct", "none"))


class LangTests(unittest.TestCase):
    def tracks(self):
        i = info(audio=(("ac3", 6), ("aac", 2), ("dts", 6)), subs=("subrip", "subrip", "hdmv_pgs_subtitle", "subrip"))
        for a, l in zip(i["audio"], ("eng", "deu", "fra")):
            a["lang"] = l
        for s, l in zip(i["subs"], ("eng", "deu", "deu", "deu")):
            s["lang"] = l
        i["subs"][3]["forced"] = True
        return i

    def test_audio_language(self):
        i = self.tracks()
        self.assertEqual(pp.preferred_tracks(i, "deu", "")[0], 1)
        self.assertEqual(pp.preferred_tracks(i, "de", "")[0], 1)                  # two-letter code
        self.assertEqual(pp.preferred_tracks(i, "ja, fra,eng", "")[0], 2)         # order of preference, first one present
        self.assertEqual(pp.preferred_tracks(i, "", "")[0], 0)                    # empty: the file's default (first, nothing marked)
        self.assertEqual(pp.preferred_tracks(i, "jpn", "")[0], 0)                 # not present: default
        i["audio"][0]["default"], i["audio"][2]["default"] = False, True
        self.assertEqual(pp.preferred_tracks(i, "", "")[0], 2)

    def test_subtitle_language(self):
        i = self.tracks()
        self.assertEqual(pp.preferred_tracks(i, "", "deu")[1], 1)                 # text track deu, not forced; the PGS track does not count
        self.assertEqual(pp.preferred_tracks(i, "", "fra")[1], None)
        self.assertEqual(pp.preferred_tracks(i, "", "")[1], 3)                     # empty: the text track marked as forced in the file
        i["subs"][0]["default"] = True
        self.assertEqual(pp.preferred_tracks(i, "", "")[1], 0)
        self.assertEqual(pp.preferred_tracks(info(audio=()), "deu", "deu"), (None, None))


class SweepTests(unittest.IsolatedAsyncioTestCase):
    """Watchdog: a process nobody takes data from anymore is ended; sessions that were never fetched expire."""

    async def test_idle_and_never_fetched(self):
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
        outside = Path(_tmp) / "outside.mkv"
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

    def test_paths(self):
        self.assertEqual(self.code("a/f.mkv"), 200)
        for bad in ("../x.mkv", "../../etc/passwd", "/etc/passwd", "a/../../x.mkv", "", "a/f.mkv\x00.txt", "a/.f.mkv.mkw-lock", ".hidden.mkv", "a/link.mkv"):
            self.assertEqual(self.code(bad), 400 if bad != "" else 400, bad)
        self.assertEqual(self.code("a/d.iso"), 415)
        self.assertEqual(self.code("a/t.txt"), 415)
        self.assertEqual(self.code("a/doesnotexist.mkv"), 404)
        self.assertEqual(self.code("a"), 415)


# ----------------------------------------------------------------- HTTP against a running dev instance
URL, OUT = os.environ.get("PLAYER_URL", ""), os.environ.get("PLAYER_OUT", "")
FILM = "Sample Movie (2019)/Sample Movie (2019).mkv"
DVD = "Sample DVD (2005)/Sample DVD (2005).mkv"


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
    """PIDs of this dev instance's ffmpeg processes (only our own, other agents may use ffmpeg at the same time)."""
    return [x["pid"] for x in json.loads(call("/api/player/sessions")[1]) if x["running"]]


def alive(pid):
    try:
        os.kill(pid, 0)
        import subprocess
        return "Z" not in subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout
    except OSError:
        return False


@unittest.skipUnless(URL, "PLAYER_URL not set (no dev instance)")
class HttpTests(unittest.TestCase):
    def test_probe_and_session_remux(self):
        s, b, _ = call("/api/player/probe?path=" + urllib.parse.quote(FILM) + "&caps=h264,aac")
        d = json.loads(b)
        self.assertEqual((s, d["plan"]["mode"], len(d["chapters"]), d["subs"][0]["kind"], d["subs"][0]["supported"]), (200, "remux", 3, "text", True))
        self.assertEqual(d["preferred"], {"audio": 0, "sub": None})
        s, d = session(FILM, client="pdt1")
        self.assertEqual(s, 200)
        s, body, h = call(d["url"])
        self.assertEqual((s, h["Content-Type"]), (200, "video/mp4"))
        self.assertGreater(len(body), 100000)
        self.assertEqual(body[4:8], b"ftyp")

    def test_seeking_starts_at_keyframe(self):
        s, d = session(FILM, client="pdt2", start=61.5)
        self.assertEqual(s, 200)
        self.assertAlmostEqual(d["start"], 52.083, places=2)

    def test_direct_range(self):
        s, d = session("Sample HEVC 10-bit (2021)/Sample HEVC 10-bit (2021).mkv", client="pdt3", caps="mkv,h264,hevc,hevc10,aac")
        self.assertEqual((s, d["mode"], d["native_seek"]), (200, "direct", True))
        s, b, h = call(d["url"], headers={"Range": "bytes=10-19"})
        self.assertEqual((s, len(b), h["Content-Range"].startswith("bytes 10-19/")), (206, 10, True))

    def test_path_escape(self):
        for bad in ("../etc/passwd", "/etc/passwd", "a/../../x.mkv", ".x.mkv"):
            for ep in ("probe", "file", "subtitle"):
                s, _, _ = call(f"/api/player/{ep}?path=" + urllib.parse.quote(bad) + "&index=0")
                self.assertEqual(s, 400, (ep, bad))
            s, _ = session(bad)
            self.assertEqual(s, 400, bad)

    def test_subtitles_webvtt(self):
        s, b, h = call("/api/player/subtitle?path=" + urllib.parse.quote(FILM) + "&index=0")
        self.assertEqual(s, 200)
        self.assertTrue(b.decode().startswith("WEBVTT"))
        self.assertIn("äöü", b.decode())                       # the sample subtitles contain non-ASCII characters
        self.assertEqual(call("/api/player/subtitle?path=" + urllib.parse.quote(FILM) + "&index=7")[0], 404)

    def test_only_one_transcode_and_cleanup(self):
        import subprocess
        s, d1 = session(DVD, client="pdtA")
        self.assertEqual((s, d1["mode"]), (200, "transcode"))
        s, d2 = session(DVD, client="pdtB")                       # another browser, the first stream not fetched yet: reserved
        self.assertEqual(s, 409)
        s, d3 = session(DVD, client="pdtA", start=5)               # the same browser replaces its stream
        self.assertEqual(s, 200)
        # fetch the stream and cut the connection after 2 s: ffmpeg must disappear
        p = subprocess.Popen(["curl", "-s", "-o", "/dev/null", "--limit-rate", "20k", URL + d3["url"]])
        time.sleep(3)
        pids = running_pids()
        self.assertEqual(len(pids), 1)
        p.kill()
        time.sleep(3)
        self.assertFalse(alive(pids[0]), "ffmpeg kept running after the connection broke off")
        s, _ = session(DVD, client="pdtB")                          # free now
        self.assertEqual(s, 200)
        call("/api/player/stop", {"client": "pdtB"})

    def test_stop_ends_stream(self):
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

    @unittest.skipUnless(OUT, "PLAYER_OUT not set")
    def test_locked_file_stays_playable(self):
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

    @unittest.skipUnless(OUT, "PLAYER_OUT not set")
    def test_symlink_to_outside(self):
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
