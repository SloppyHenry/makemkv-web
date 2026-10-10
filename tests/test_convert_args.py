import unittest

from tests import env  # noqa: F401
from app import ffmpeg_args as fa
from app.convert_schema import clean_v2

INFO = {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "r_frame_rate": "24000/1001"},
                    {"codec_type": "audio", "channels": 6, "bit_rate": "640000"}, {"codec_type": "audio", "channels": 2}, {"codec_type": "audio", "channels": 8},
                    {"codec_type": "subtitle", "tags": {"language": "deu"}, "disposition": {"forced": 0}},
                    {"codec_type": "subtitle", "tags": {"language": "eng"}, "disposition": {"forced": 1}},
                    {"codec_type": "subtitle", "tags": {"language": "fra"}, "disposition": {"forced": 0}}], "format": {"duration": "7200"}}
HDR = {"streams": [{"codec_type": "video", "codec_name": "hevc", "width": 3840, "height": 2160, "r_frame_rate": "24/1", "color_transfer": "smpte2084",
                    "color_primaries": "bt2020", "color_space": "bt2020nc"}, {"codec_type": "audio", "channels": 8}], "format": {"duration": "7200"}}


def old_x265(cfg, pools=0):          # Stand vor Schema v2 (zum Vergleich: für alte Einstellungen muss der Befehl gleich bleiben)
    a = ["-c:v", "libx265", "-preset", cfg["preset"], "-crf", str(cfg["rf"]), "-pix_fmt", "yuv420p10le"]
    if cfg["tune"] in ("grain", "animation"):
        a += ["-tune", cfg["tune"]]
    params = ["log-level=error"] + ([f"pools={pools}"] if pools else []) + ([cfg["extra"]] if cfg["extra"] else [])
    return a + ["-x265-params", ":".join(params)]


def old_audio(cfg, info):
    auds = [x for x in info["streams"] if x["codec_type"] == "audio"]
    if cfg["audio"] == "copy" or not auds:
        return ["-c:a", "copy"]
    a = []
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


def old_cmd(src, out, cfg, info, crop):
    a = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src), "-map", "0:v:0", "-map", "0:a?", "-map", "0:s?", "-map_chapters", "0"]
    if crop:
        a += ["-vf", crop]
    return a + old_x265(cfg) + ["-fps_mode", "cfr"] + old_audio(cfg, info) + ["-c:s", "copy", "-progress", "pipe:1", "-nostats", str(out)]


def ctx(info=INFO, **kw):
    return {"info": info, "crop": None, "scan": "progressive", "hdr": {}, "pools": 0, "kbps": 0, **kw}


class ArgsTest(unittest.TestCase):
    def test_alte_einstellungen_geben_denselben_befehl(self):
        for v1 in ({"rf": 21, "preset": "slow", "tune": "none", "extra": "aq-mode=3:no-sao=1", "audio": "copy"},
                   {"rf": 18, "preset": "veryslow", "tune": "grain", "extra": "", "audio": "aac"},
                   {"rf": 25, "preset": "fast", "tune": "film", "extra": "a=1:b=2", "audio": "opus"},
                   {"rf": 20, "preset": "medium", "tune": "animation", "extra": "no-sao=1", "audio": "ac3"},
                   {"rf": 20, "preset": "medium", "tune": "stillimage", "extra": "", "audio": "eac3"}):
            for crop in (None, "crop=1920:800:0:140"):
                cfg = clean_v2({**v1, "convert": True})
                new = fa.ffmpeg_args("a.mkv", "b.mkv", cfg, ctx(crop=crop))
                i = new.index("-metadata")
                self.assertTrue(new[i + 1].startswith("MKW_CONVERTED="))
                self.assertEqual(new[:i] + new[i + 2:], old_cmd("a.mkv", "b.mkv", v1, INFO, crop), (v1, crop))

    def test_segment_pools(self):
        cfg = clean_v2({"rf": 20})
        self.assertIn("log-level=error:pools=4:aq-mode=3:no-sao=1", fa.x265_args(cfg, ctx(pools=4)))

    def test_x264(self):
        cfg = clean_v2({"v": 2, "video": {"codec": "x264", "speed": "medium", "tune": "film", "extra": "ref=4"}, "quality": {"crf": 18}})
        a = fa.video_args(cfg, ctx())
        self.assertEqual(a[:8], ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p10le"])
        self.assertIn("film", a)
        self.assertEqual(a[-2:], ["-x264-params", "ref=4"])

    def test_svtav1(self):
        cfg = clean_v2({"v": 2, "video": {"codec": "svtav1", "speed": "8", "tune": "grain", "extra": "enable-tf=0"}, "quality": {"crf": 30}})
        a = fa.video_args(cfg, ctx(pools=6))
        self.assertEqual(a[:6], ["-c:v", "libsvtav1", "-preset", "8", "-crf", "30"])
        self.assertEqual(a[-1], "tune=0:lp=6:film-grain=8:enable-tf=0")

    def test_hardware(self):
        va = clean_v2({"v": 2, "video": {"codec": "hw", "hw": "hevc_vaapi"}, "quality": {"crf": 23}})
        self.assertEqual(fa.global_args(va), ["-vaapi_device", fa.HW_DEVICE])
        self.assertEqual(fa.filter_chain(va, ctx())[-2:], ["format=p010le", "hwupload"])
        self.assertEqual(fa.video_args(va, ctx())[:2], ["-c:v", "hevc_vaapi"])
        self.assertIn("-qp", fa.video_args(va, ctx()))
        h264 = clean_v2({"v": 2, "video": {"codec": "hw", "hw": "h264_qsv"}})
        self.assertEqual(fa.filter_chain(h264, ctx()), ["format=nv12"])
        self.assertEqual(fa.global_args(h264), [])
        nv = clean_v2({"v": 2, "video": {"codec": "hw", "hw": "hevc_nvenc"}, "quality": {"crf": 24}})
        self.assertIn("-cq", fa.video_args(nv, ctx()))

    def test_remux(self):
        cfg = clean_v2({"v": 2, "video": {"codec": "copy"}, "sound": {"mode": "aac"}})
        a = fa.ffmpeg_args("a.mkv", "b.mkv", cfg, ctx())
        self.assertIn("copy", a)
        self.assertNotIn("-vf", a)
        self.assertNotIn("libx265", a)
        self.assertIn("aac", a)

    def test_filter_reihenfolge(self):
        cfg = clean_v2({"v": 2, "picture": {"scale": "720", "denoise": "light", "deint": "on"}})
        f = fa.filter_chain(cfg, ctx(crop="crop=1920:800:0:140"))
        self.assertEqual([x.split("=")[0] for x in f], ["bwdif", "crop", "hqdn3d", "scale"])
        self.assertIn("min(ih\\,720)", f[-1])
        self.assertEqual(fa.filter_chain(clean_v2({"v": 2, "picture": {"crop": "off"}}), ctx(crop="crop=1:1:0:0")), [])
        man = clean_v2({"v": 2, "picture": {"crop": "manual", "crop_manual": "1920:800:0:140"}})
        self.assertEqual(fa.filter_chain(man, ctx(crop="crop=9:9:0:0")), ["crop=1920:800:0:140"])

    def test_deinterlace_auto(self):
        cfg = clean_v2({"v": 2, "picture": {"deint": "auto"}})
        self.assertEqual(fa.deint_filter(cfg, ctx(scan="progressive")), "")
        self.assertTrue(fa.deint_filter(cfg, ctx(scan="interlaced")).startswith("bwdif"))
        self.assertTrue(fa.deint_filter(cfg, ctx(scan="telecine")).endswith("decimate"))
        self.assertTrue(fa.changes_framecount(cfg, ctx(scan="telecine")))
        self.assertFalse(fa.changes_framecount(cfg, ctx(scan="interlaced")))

    def test_ton(self):
        st = clean_v2({"v": 2, "sound": {"mode": "aac", "channels": "stereo"}})
        a = fa.audio_args(st, INFO)
        self.assertIn("-ac:a:0", a)                      # 5.1 -> Stereo
        self.assertNotIn("-ac:a:1", a)                   # Stereo bleibt
        self.assertEqual(a.count("160k"), 3)
        five = clean_v2({"v": 2, "sound": {"mode": "opus", "channels": "51", "kbps": 300}})
        b = fa.audio_args(five, INFO)
        self.assertEqual(b[b.index("-ac:a:2") + 1], "6")
        self.assertIn("300k", b)
        self.assertEqual(fa.audio_args(clean_v2({"v": 2}), INFO), ["-c:a", "copy"])

    def test_untertitel(self):
        sc = lambda m, l="": clean_v2({"v": 2, "subs": {"mode": m, "langs": l}})      # noqa: E731
        self.assertEqual(fa.sub_maps(sc("all"), INFO), ["-map", "0:s?"])
        self.assertEqual(fa.sub_maps(sc("none"), INFO), [])
        self.assertEqual(fa.sub_streams(sc("forced"), INFO), [1])
        self.assertEqual(fa.sub_streams(sc("langs", "deu,eng"), INFO), [0, 1])
        self.assertEqual(fa.sub_maps(sc("langs", "fra"), INFO), ["-map", "0:s:2"])

    def test_hdr(self):
        cfg = clean_v2({"v": 2, "video": {"codec": "x265", "speed": "medium", "extra": "aq-mode=3"}, "quality": {"crf": 22}})
        h = {"master": "G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1)", "cll": "1000,400"}
        p = fa.x265_args(cfg, ctx(HDR, hdr=h))[-1]
        for want in ("colorprim=bt2020", "transfer=smpte2084", "colormatrix=bt2020nc", "hdr10-opt=1", "repeat-headers=1", "master-display=G(13250", "max-cll=1000,400"):
            self.assertIn(want, p)
        self.assertNotIn("hdr10", fa.x265_args(cfg, ctx(INFO))[-1])                 # SDR-Quelle: nichts davon
        self.assertEqual(fa.hdr_problem(clean_v2({"v": 2, "video": {"codec": "x264"}}), HDR) != "", True)
        self.assertEqual(fa.hdr_problem(cfg, HDR), "")
        self.assertEqual(fa.hdr_problem(clean_v2({"v": 2, "video": {"codec": "x264"}, "picture": {"hdr": "tonemap"}}), HDR), "")
        tm = clean_v2({"v": 2, "picture": {"hdr": "tonemap"}})
        self.assertTrue(any(x.startswith("zscale") for x in fa.filter_chain(tm, ctx(HDR))))
        self.assertNotIn("hdr10", fa.x265_args(tm, ctx(HDR))[-1])

    def test_zielgroesse_und_zwei_durchgaenge(self):
        cfg = clean_v2({"v": 2, "video": {"codec": "x265"}, "quality": {"mode": "size", "size_gb": 4}, "sound": {"mode": "aac"}})
        k = fa.target_kbps(cfg, INFO, 7200)
        self.assertTrue(4000 < k < 5000, k)               # 4 GB über 2 h abzüglich Ton
        self.assertTrue(fa.two_pass(cfg))
        c1 = fa.ffmpeg_args("a.mkv", "b.mkv", cfg, ctx(kbps=k, passlog="/t/p"), 1)
        c2 = fa.ffmpeg_args("a.mkv", "b.mkv", cfg, ctx(kbps=k, passlog="/t/p"), 2)
        self.assertIn("-an", c1)
        self.assertIn("null", c1)
        self.assertIn("pass=1", c1[c1.index("-x265-params") + 1])
        self.assertIn("pass=2", c2[c2.index("-x265-params") + 1])
        self.assertIn(f"{k}k", c2)
        self.assertNotIn("-crf", c2)
        sv = clean_v2({"v": 2, "video": {"codec": "svtav1"}, "quality": {"mode": "bitrate", "kbps": 3000}})
        self.assertFalse(fa.two_pass(sv))
        self.assertIn("3000k", fa.video_args(sv, ctx(kbps=3000)))

    def test_vorschau(self):
        s = fa.command_preview(clean_v2({"rf": 20}))
        self.assertTrue(s.startswith("ffmpeg"))
        self.assertIn("libx265", s)
        two = fa.command_preview(clean_v2({"v": 2, "quality": {"mode": "bitrate", "kbps": 3000}}))
        self.assertEqual(len(two.splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
