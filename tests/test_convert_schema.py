import unittest

from tests import env  # noqa: F401
from app.convert_schema import (CODECS, clean_v2, crf_to_level, default_v2, describe, is_v1_compatible, level_to_crf, to_v1,
                                translate_quality)


class SchemaTest(unittest.TestCase):
    def test_v1_wird_migriert(self):
        d = clean_v2({"convert": True, "rf": 19, "preset": "medium", "tune": "grain", "extra": "aq-mode=2", "audio": "aac"})
        self.assertEqual(d["v"], 2)
        self.assertEqual((d["video"]["codec"], d["video"]["bits"], d["video"]["speed"], d["video"]["tune"], d["video"]["extra"]), ("x265", 10, "medium", "grain", "aq-mode=2"))
        self.assertEqual((d["quality"]["mode"], d["quality"]["crf"], d["sound"]["mode"]), ("crf", 19, "aac"))
        self.assertTrue(d["convert"])
        self.assertEqual({k: d[k] for k in ("rf", "preset", "tune", "extra", "audio")}, {"rf": 19, "preset": "medium", "tune": "grain", "extra": "aq-mode=2", "audio": "aac"})

    def test_v1_ungueltiges_wird_ersetzt(self):
        d = clean_v2({"rf": 99, "preset": "bogus", "tune": "x", "extra": "rm -rf;", "audio": "dts"})
        self.assertEqual((d["quality"]["crf"], d["video"]["speed"], d["video"]["tune"], d["sound"]["mode"]), (30, "slow", "none", "copy"))
        self.assertEqual(d["video"]["extra"], "aq-mode=3:no-sao=1")

    def test_idempotent_und_vollstaendig(self):
        d = clean_v2({"rf": 22})
        self.assertEqual(clean_v2(d), d)
        self.assertEqual(clean_v2(None)["video"]["codec"], "x265")
        self.assertEqual(clean_v2("quatsch")["quality"]["crf"], 21)

    def test_alte_oberflaeche_aendert_gespeichertes_v2(self):
        d = clean_v2({"v": 2, "video": {"codec": "x265", "speed": "slow"}, "quality": {"crf": 20}})
        d.update(rf=24, audio="opus")                         # nur die alten Felder ändern sich
        n = clean_v2(d)
        self.assertEqual((n["quality"]["crf"], n["sound"]["mode"], n["rf"]), (24, "opus", 24))

    def test_alte_felder_wirken_nicht_bei_anderem_codec(self):
        d = clean_v2({"v": 2, "video": {"codec": "svtav1", "speed": "6"}, "quality": {"crf": 30}})
        d["rf"] = 18
        self.assertEqual(clean_v2(d)["quality"]["crf"], 30)

    def test_v2_pruefung(self):
        d = clean_v2({"v": 2, "video": {"codec": "svtav1", "bits": 8, "speed": "99", "extra": "a b"}, "quality": {"mode": "size", "size_gb": 0},
                      "picture": {"scale": "4k", "crop": "manual", "deint": "x"}, "sound": {"mode": "mp3", "kbps": 99999}, "subs": {"mode": "langs", "langs": "DE"}})
        self.assertEqual((d["video"]["codec"], d["video"]["bits"], d["video"]["speed"], d["video"]["extra"]), ("svtav1", 8, "6", ""))
        self.assertEqual(d["quality"]["mode"], "crf")                 # Zielgröße 0 ist unbrauchbar
        self.assertEqual((d["picture"]["scale"], d["picture"]["crop"], d["picture"]["deint"]), ("keep", "auto", "off"))
        self.assertEqual((d["sound"]["mode"], d["subs"]["mode"]), ("copy", "all"))
        h = clean_v2({"v": 2, "video": {"codec": "hw", "hw": "hevc_vaapi; rm"}})
        self.assertEqual(h["video"]["hw"], "hevc_vaapi")
        self.assertEqual(clean_v2({"v": 2, "video": {"codec": "hw", "hw": "h264_qsv"}})["video"]["bits"], 8)

    def test_crf_je_codec_begrenzt(self):
        self.assertEqual(clean_v2({"v": 2, "video": {"codec": "x264"}, "quality": {"crf": 200}})["quality"]["crf"], 40)
        self.assertEqual(clean_v2({"v": 2, "video": {"codec": "svtav1"}, "quality": {"crf": 1}})["quality"]["crf"], 8)

    def test_verbund_vertraeglichkeit(self):
        self.assertTrue(is_v1_compatible(clean_v2({"rf": 20, "audio": "aac"})))
        for change in ({"video": {"codec": "x264"}}, {"video": {"codec": "x265", "bits": 8}}, {"quality": {"mode": "bitrate", "kbps": 3000}},
                       {"picture": {"scale": "720"}}, {"picture": {"denoise": "light"}}, {"sound": {"mode": "aac", "channels": "stereo"}}, {"subs": {"mode": "none"}}):
            self.assertFalse(is_v1_compatible(clean_v2({"v": 2, **change})), change)
        self.assertEqual(set(to_v1(clean_v2({"rf": 20}))), {"convert", "rf", "preset", "tune", "extra", "audio"})

    def test_qualitaetsskala(self):
        for c in ("x265", "x264", "svtav1", "hw"):
            w, b = CODECS[c]["q"]
            self.assertEqual(level_to_crf(c, 0), w)
            self.assertEqual(level_to_crf(c, 100), b)
            self.assertAlmostEqual(crf_to_level(c, level_to_crf(c, 62)), 62, delta=4)
        self.assertEqual(translate_quality(20, "x265", "x264"), 18)
        self.assertEqual(translate_quality(20, "x265", "x265"), 20)
        self.assertLess(translate_quality(16, "x265", "x264"), translate_quality(24, "x265", "x264"))      # besser = kleinere Zahl

    def test_beschreibung(self):
        self.assertIn("RF 20", describe(clean_v2({"rf": 20})))
        self.assertIn("720p", describe(clean_v2({"v": 2, "picture": {"scale": "720"}})))
        self.assertEqual(default_v2()["v"], 2)


if __name__ == "__main__":
    unittest.main()
