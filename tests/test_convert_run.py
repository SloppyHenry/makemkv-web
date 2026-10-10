"""Echte Konvertierungen mit den Beispieldateien (braucht ffmpeg/ffprobe und scripts/dev.sh-Beispiele); überspringt sich sonst."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from tests import env
from app import convert, convert_caps
from app.config import SEG_MIN_SECONDS
from app.convert_schema import clean_v2
from app.state import settings

FILM = env.SAMPLES / "Beispielfilm (2019)" / "Beispielfilm (2019).mkv"
DVD = env.SAMPLES / "Beispiel DVD (2005)" / "Beispiel DVD (2005).mkv"
SERIE = env.SAMPLES / "The Walking Dead - Disc 1" / "The Walking Dead - Disc 1 - Titel 01.mkv"
HAVE = shutil.which("ffmpeg") and FILM.exists() and DVD.exists() and SERIE.exists()
_n = [100]


def streams(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", "-show_chapters", str(p)], capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    return d, {t: [s for s in d["streams"] if s["codec_type"] == t] for t in ("video", "audio", "subtitle")}


def item(src, cfg):
    _n[0] += 1
    return {"id": _n[0], "name": src.name, "src": str(src), "cfg": clean_v2({**cfg, "convert": True}), "status": "queued", "origin": "", "size_in": src.stat().st_size,
            "dev": "", "folder": "t", "pct": 0.0}


@unittest.skipUnless(HAVE, "ffmpeg oder Beispieldateien fehlen (scripts/dev.sh start erzeugt sie)")
class RunTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        import asyncio
        asyncio.run(convert_caps.probe_capabilities())

    async def run_cfg(self, src, cfg, nseg_setting=1):
        settings["conv_segments"] = nseg_setting
        it = item(src, cfg)
        out = await convert.convert_one(it)
        d, s = streams(out)
        self.assertTrue(out.exists())
        return it, d, s

    async def test_v1_standard_x265(self):
        it, d, s = await self.run_cfg(FILM, {"rf": 28, "preset": "ultrafast", "tune": "none", "extra": "", "audio": "aac"})
        v = s["video"][0]
        self.assertEqual((v["codec_name"], v["pix_fmt"]), ("hevc", "yuv420p10le"))
        self.assertEqual(s["audio"][0]["codec_name"], "aac")
        self.assertEqual(len(s["subtitle"]), 1)
        self.assertEqual(len(d["chapters"]), 3)
        self.assertEqual(it["meta"]["nseg"], 1)

    async def test_x264_8bit_und_skalieren(self):
        _, _, s = await self.run_cfg(DVD, {"v": 2, "video": {"codec": "x264", "bits": 8, "speed": "ultrafast"}, "quality": {"crf": 28}, "picture": {"scale": "480", "crop": "off"}})
        v = s["video"][0]
        self.assertEqual((v["codec_name"], v["pix_fmt"], v["height"]), ("h264", "yuv420p", 480))
        self.assertEqual(s["audio"][0]["codec_name"], "ac3")                 # Ton kopiert

    async def test_scale_hochskalieren_nie(self):
        _, _, s = await self.run_cfg(FILM, {"v": 2, "video": {"codec": "x264", "speed": "ultrafast"}, "quality": {"crf": 30}, "picture": {"scale": "720", "crop": "off"}})
        self.assertEqual(s["video"][0]["height"], 480)

    async def test_svtav1_10bit(self):
        if "libsvtav1" not in convert_caps.caps["encoders"]:
            self.skipTest("kein libsvtav1")
        _, _, s = await self.run_cfg(FILM, {"v": 2, "video": {"codec": "svtav1", "speed": "12"}, "quality": {"crf": 40}, "sound": {"mode": "opus", "channels": "stereo"}})
        v = s["video"][0]
        self.assertEqual((v["codec_name"], v["pix_fmt"]), ("av1", "yuv420p10le"))
        self.assertEqual(s["audio"][0]["codec_name"], "opus")

    async def test_nur_remuxen_mit_tonwandlung_und_untertitelfilter(self):
        it, d, s = await self.run_cfg(FILM, {"v": 2, "video": {"codec": "copy"}, "sound": {"mode": "aac"}, "subs": {"mode": "none"}})
        self.assertEqual(s["video"][0]["codec_name"], "h264")               # Bild unverändert
        self.assertEqual(s["audio"][0]["codec_name"], "aac")
        self.assertEqual(len(s["subtitle"]), 0)
        self.assertEqual(len(d["chapters"]), 3)

    async def test_zeilensprung_und_entrauschen(self):
        _, _, s = await self.run_cfg(DVD, {"v": 2, "video": {"codec": "x264", "bits": 8, "speed": "ultrafast"}, "quality": {"crf": 30},
                                          "picture": {"deint": "on", "denoise": "medium", "crop": "off"}})
        self.assertEqual(s["video"][0]["codec_name"], "h264")

    async def test_zielgroesse_zwei_durchgaenge(self):
        it, _, s = await self.run_cfg(DVD, {"v": 2, "video": {"codec": "x264", "speed": "veryfast", "bits": 8}, "quality": {"mode": "bitrate", "kbps": 600},
                                          "picture": {"crop": "off"}})
        size = Path(convert.CONV_WORK / f"{it['id']}.mkv").stat().st_size
        self.assertTrue(1_800_000 < size < 4_000_000, size)                   # 30 s bei ca. 600 kb/s + AC3-Ton (rund 2,2 + 0,7 MB)
        self.assertEqual(list(convert.CONV_WORK.glob(f"{it['id']}-pass*")), [])   # Protokolldateien aufgeräumt

    async def test_x265_bitrate_zwei_durchgaenge(self):
        _, _, s = await self.run_cfg(DVD, {"v": 2, "video": {"codec": "x265", "speed": "ultrafast"}, "quality": {"mode": "bitrate", "kbps": 500}, "picture": {"crop": "off"}})
        self.assertEqual(s["video"][0]["codec_name"], "hevc")

    async def test_segmente_mit_allen_software_codecs(self):
        self.assertGreater(2652, SEG_MIN_SECONDS)
        for cfg, name in (({"rf": 30, "preset": "ultrafast", "tune": "none", "extra": "", "audio": "copy"}, "x265"),
                          ({"v": 2, "video": {"codec": "x264", "speed": "ultrafast", "bits": 8}, "quality": {"crf": 30}}, "x264"),
                          ({"v": 2, "video": {"codec": "svtav1", "speed": "13"}, "quality": {"crf": 45}}, "svtav1")):
            if name == "svtav1" and "libsvtav1" not in convert_caps.caps["encoders"]:
                continue
            it, d, s = await self.run_cfg(SERIE, cfg, nseg_setting=3)
            self.assertEqual(it["meta"]["nseg"], 3, name)
            self.assertAlmostEqual(float(d["format"]["duration"]), 2652, delta=2)
            self.assertEqual(len(s["audio"]), 1)

    async def test_hardware_wenn_vorhanden(self):
        hw = [e for e in convert_caps.caps["hw"] if e.startswith("hevc_")]
        if not hw:
            self.skipTest("kein Hardware-Encoder gemeldet")
        it, _, s = await self.run_cfg(FILM, {"v": 2, "video": {"codec": "hw", "hw": hw[0]}, "quality": {"crf": 28}}, nseg_setting=3)
        self.assertEqual(s["video"][0]["codec_name"], "hevc")
        self.assertEqual(it["meta"]["nseg"], 1)

    async def test_nicht_unterstuetztes_wird_abgelehnt(self):
        with self.assertRaises(convert.Unsupported):
            await convert.convert_one(item(FILM, {"v": 2, "video": {"codec": "hw", "hw": "hevc_nvenc"}}))
        hdr = {"streams": [{"codec_type": "video", "color_transfer": "smpte2084"}], "format": {"duration": "1"}}
        self.assertTrue(convert_caps.unusable(clean_v2({"v": 2, "video": {"codec": "x264"}}), hdr))            # HDR ginge verloren
        self.assertEqual(convert_caps.unusable(clean_v2({"v": 2, "video": {"codec": "x265"}}), hdr), "")

    async def test_probe(self):
        from app import convert_probe
        job = {"id": "t1", "status": "running", "t": 0}
        await convert_probe.run(job, FILM, clean_v2({"v": 2, "video": {"codec": "x264", "speed": "ultrafast", "bits": 8}, "quality": {"crf": 30}, "picture": {"crop": "off"}}))
        self.assertEqual(job["status"], "done", job.get("error"))
        r = job["result"]
        self.assertTrue(r["before"].startswith("data:image/jpeg;base64,") and r["after"].startswith("data:image/jpeg;base64,"))
        self.assertTrue(0 < r["out_bytes"] < 10 * r["in_bytes"])
        self.assertEqual(list(convert.CONV_WORK.glob("probe-*")), [])
        bad = {"id": "t2", "status": "running", "t": 0}
        await convert_probe.run(bad, FILM, clean_v2({"v": 2, "video": {"codec": "copy"}}))
        self.assertEqual(bad["status"], "error")

    async def test_falsche_spurzahl_wird_nicht_gemeldet(self):
        # Untertitel „nur erzwungene“ ohne erzwungene Spur: erwartet 0 Untertitel, Ergebnis stimmt überein
        _, _, s = await self.run_cfg(FILM, {"v": 2, "video": {"codec": "copy"}, "subs": {"mode": "forced"}})
        self.assertEqual(len(s["subtitle"]), 0)


if __name__ == "__main__":
    unittest.main()
