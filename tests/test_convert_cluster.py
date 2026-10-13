import asyncio
import unittest
from unittest import mock

from tests import env  # noqa: F401
from app import convert, convert_caps, convert_presets, convert_stats, settings as settings_mod
from app.convert_schema import clean_v2
from app.state import settings

OLD = {"name": "secondtux", "reachable": True, "capabilities": {}, "legacy": True, "has_handover": True, "cores": 8}
NEW = {"name": "maintux", "reachable": True, "legacy": False, "has_handover": True, "cores": 32, "load": 1.0,
       "capabilities": {"version": "0.4.0", "convert": {"schema": 2, "codecs": ["x265", "x264", "svtav1", "copy"], "hw": [], "hw10": [], "audio": ["aac", "opus", "ac3", "eac3"],
                                                        "filters": ["bwdif", "hqdn3d", "idet", "yadif", "fieldmatch", "decimate"], "cores": 32, "speed": {"x265": 1.0}}}}


class PeerTest(unittest.TestCase):
    def test_old_machine_only_with_v1_jobs(self):
        v1 = clean_v2({"rf": 20, "audio": "aac"})
        self.assertEqual(convert_caps.peer_ok(v1, OLD), (True, ""))
        for c in ({"video": {"codec": "x264"}}, {"picture": {"scale": "720"}}, {"sound": {"mode": "aac", "channels": "stereo"}}, {"quality": {"mode": "bitrate", "kbps": 2000}}):
            ok, why = convert_caps.peer_ok(clean_v2({"v": 2, **c}), OLD)
            self.assertFalse(ok)
            self.assertIn("older version", why)

    def test_new_machine_checks_encoders_and_filters(self):
        self.assertTrue(convert_caps.peer_ok(clean_v2({"v": 2, "video": {"codec": "svtav1"}}), NEW)[0])
        ok, why = convert_caps.peer_ok(clean_v2({"v": 2, "video": {"codec": "hw", "hw": "hevc_vaapi"}}), NEW)
        self.assertFalse(ok)
        self.assertIn("hardware", why)
        ok, why = convert_caps.peer_ok(clean_v2({"v": 2, "picture": {"hdr": "tonemap"}}), NEW)
        self.assertFalse(ok)
        self.assertIn("zscale", why)
        self.assertFalse(convert_caps.peer_ok(clean_v2({"v": 2}), {**NEW, "reachable": False})[0])
        self.assertFalse(convert_caps.peer_ok(clean_v2({"v": 2, "video": {"codec": "x264"}, "sound": {"mode": "opus"}}), {**NEW, "capabilities": {"convert": {**NEW["capabilities"]["convert"], "audio": ["aac"]}}})[0])


class WorkerTest(unittest.IsolatedAsyncioTestCase):
    async def test_simultaneous_files(self):
        """ensure_conv_workers() used to never start further workers: "files at the same time" > 1 had no effect."""
        state = {"now": 0, "peak": 0, "done": 0}

        async def fake(item):
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
            await asyncio.sleep(0.25)
            state["now"] -= 1
            state["done"] += 1
        q = asyncio.Queue()
        with mock.patch.object(convert, "process_item", fake), mock.patch.object(convert, "convert_queue", q):
            convert.conv_running = 0
            settings["conv_parallel"] = 3
            main = asyncio.create_task(convert.convert_worker())
            for i in range(6):
                q.put_nowait({"id": i})
            await asyncio.sleep(0.1)
            self.assertEqual(convert.conv_running, 3)
            await asyncio.sleep(0.7)
            self.assertEqual((state["peak"], state["done"]), (3, 6))
            # raise at runtime (as after saving the settings)
            settings["conv_parallel"] = 5
            convert.ensure_conv_workers()
            self.assertEqual(convert.conv_running, 5)
            state["peak"] = 0
            for i in range(10):
                q.put_nowait({"id": 10 + i})
            await asyncio.sleep(0.9)
            self.assertEqual(state["peak"], 5)
            # reduce: surplus workers end themselves as soon as it is their turn again
            settings["conv_parallel"] = 1
            for i in range(8):
                q.put_nowait({"id": 30 + i})
            await asyncio.sleep(1.2)
            self.assertEqual(convert.conv_running, 1)
            main.cancel()
            convert.conv_running = 0

    async def test_error_does_not_end_worker(self):
        async def broken(item):
            raise RuntimeError("cleanup error")
        q = asyncio.Queue()
        with mock.patch.object(convert, "process_item", broken), mock.patch.object(convert, "convert_queue", q):
            convert.conv_running = 0
            settings["conv_parallel"] = 1
            t = asyncio.create_task(convert.convert_worker())
            it = {"id": 1, "status": "running", "error": ""}
            q.put_nowait(it)
            await asyncio.sleep(0.2)
            self.assertEqual(it["status"], "error")
            self.assertFalse(t.done())
            t.cancel()
            convert.conv_running = 0


class EstimateTest(unittest.TestCase):
    SRC = {"size": 24 * 1024 ** 3, "dur": 7200.0, "w": 1920, "h": 1080, "fps": 23.976, "audio": ["dts 6ch", "ac3 6ch"]}

    def setUp(self):
        convert_stats.records.clear()

    def test_size_plausible_and_monotonic(self):
        a = convert_stats.model_bytes(clean_v2({"rf": 20}), self.SRC)
        self.assertTrue(0.12 < a / self.SRC["size"] < 0.5, a / self.SRC["size"])
        self.assertGreater(convert_stats.model_bytes(clean_v2({"rf": 18}), self.SRC), a)
        self.assertLess(convert_stats.model_bytes(clean_v2({"rf": 24}), self.SRC), a)
        self.assertLess(convert_stats.model_bytes(clean_v2({"v": 2, "picture": {"scale": "720"}, "quality": {"crf": 20}}), self.SRC), a)
        self.assertGreater(convert_stats.model_bytes(clean_v2({"v": 2, "video": {"tune": "grain", "extra": ""}, "quality": {"crf": 20}}), self.SRC), a)
        self.assertEqual(convert_stats.model_bytes(clean_v2({"v": 2, "quality": {"mode": "size", "size_gb": 5}}), self.SRC), 5 * 1024 ** 3)

    def test_time_slower_with_slow_preset_and_few_cores(self):
        fast, slow = clean_v2({"v": 2, "video": {"speed": "fast"}}), clean_v2({"v": 2, "video": {"speed": "veryslow"}})
        t = lambda c, n: convert_stats.estimate_secs(c, self.SRC, n)[0]      # noqa: E731
        self.assertGreater(t(slow, 8), t(fast, 8))
        self.assertGreater(t(fast, 4), t(fast, 32))

    def test_statistics_calibrate(self):
        cfg = clean_v2({"rf": 20})
        base, n = convert_stats.estimate_size(cfg, self.SRC)
        self.assertEqual(n, 0)
        for _ in range(3):             # three times the result is twice as large as the model expected
            convert_stats.records.append({"family": "x265", "model": base, "size_out": base * 2, "node": "test-f", "norm": 0.5, "t": 0})
        est, n = convert_stats.estimate_size(cfg, self.SRC)
        self.assertEqual(n, 3)
        self.assertAlmostEqual(est / base, 2.0, delta=0.01)
        t1, k1 = convert_stats.estimate_secs(cfg, self.SRC, 8)
        self.assertEqual(k1, 3)
        self.assertGreater(t1, 0)
        self.assertEqual(convert_stats.speed_table(), {"x265": 0.5})

    def test_record_writes_file(self):
        it = {"cfg": clean_v2({"rf": 20}), "meta": {"dur": 100.0, "w": 1920, "h": 1080, "fps": 24.0, "nseg": 1}, "started": __import__("time").time() - 50, "size_in": 10 ** 9, "size_out": 3 * 10 ** 8}
        convert_stats.record(it)
        self.assertEqual(len(convert_stats.records), 1)
        self.assertTrue(convert_stats.STATS.exists())
        convert_stats.records.clear()
        convert_stats.load()
        self.assertEqual(len(convert_stats.records), 1)


class PresetTest(unittest.TestCase):
    def setUp(self):
        settings_mod.settings.update({"convert": convert_presets.ConvertSettings().model_dump()})
        settings["presets"] = {k: clean_v2(v) for k, v in {"bluray": {"rf": 21, "preset": "slow", "tune": "none", "extra": "aq-mode=3:no-sao=1", "audio": "copy"},
                                                            "dvd": {"rf": 21, "preset": "slow", "tune": "none", "extra": "aq-mode=3:no-sao=1", "audio": "copy"}}.items()}

    def test_builtin(self):
        ids = [p["id"] for p in convert_presets.all_presets()]
        self.assertEqual(ids[:6], ["dvd", "bluray", "animation", "grain", "uhd", "small"])
        for p in convert_presets.BUILTIN:
            self.assertEqual(p["cfg"], clean_v2(p["cfg"]), p["id"])
            self.assertTrue(p["cfg"]["convert"])
        by = {p["id"]: p["cfg"] for p in convert_presets.BUILTIN}
        self.assertEqual((by["animation"]["video"]["tune"], by["grain"]["video"]["tune"]), ("animation", "grain"))
        self.assertEqual(by["small"]["picture"]["scale"], "720")
        self.assertEqual(by["dvd"]["picture"]["deint"], "auto")

    def test_untouched_default_is_new_preset(self):
        d = convert_presets.default_for("bluray")
        self.assertEqual((d["id"], d["cfg"]["quality"]["crf"]), ("bluray", 20))
        self.assertEqual(convert_presets.default_for("uhd")["id"], "uhd")

    def test_nvidia_card_preselects_nvidia_presets(self):
        with mock.patch.dict(convert_caps.caps, {"hw10": ["hevc_nvenc"]}):
            self.assertEqual(convert_presets.default_for("bluray")["id"], "bluray-nvenc")
            self.assertEqual(convert_presets.default_for("dvd")["id"], "dvd-x265")
            self.assertEqual(convert_presets.default_for("uhd")["id"], "uhd")
        with mock.patch.dict(convert_caps.caps, {"hw10": ["hevc_vaapi"]}):
            self.assertEqual(convert_presets.default_for("bluray")["id"], "bluray")

    def test_custom_default_from_old_interface_stays(self):
        settings["presets"]["bluray"] = clean_v2({"rf": 23, "preset": "medium", "tune": "none", "extra": "", "audio": "aac"})
        d = convert_presets.default_for("bluray")
        self.assertEqual((d["id"], d["cfg"]["quality"]["crf"]), ("", 23))

    def test_custom_presets_and_default_choice(self):
        with mock.patch.object(convert_presets, "save_conf"):
            p = convert_presets.api_preset_create(convert_presets.PresetReq(name="Series lean", cfg={"v": 2, "quality": {"crf": 24}}))
            self.assertEqual(p["id"], "series-lean")
            self.assertEqual(p["cfg"]["origin"], "series-lean")
            p2 = convert_presets.api_preset_create(convert_presets.PresetReq(name="Series lean"))
            self.assertEqual(p2["id"], "series-lean-2")
            convert_presets.api_default(convert_presets.DefaultReq(kind="dvd", preset="series-lean"))
            self.assertEqual(convert_presets.default_for("dvd")["id"], "series-lean")
            self.assertEqual(settings["presets"]["dvd"]["quality"]["crf"], 24)              # the old flat fields follow
            self.assertEqual(settings["presets"]["dvd"]["rf"], 24)
            convert_presets.api_preset_delete("series-lean")
            self.assertNotIn("dvd", convert_presets.conf()["default_for"])
            with self.assertRaises(Exception):
                convert_presets.api_preset_delete("bluray")
            with self.assertRaises(Exception):
                convert_presets.api_preset_update("bluray", convert_presets.PresetReq(name="x"))

    def test_settings_model_validates(self):
        m = convert_presets.ConvertSettings(presets={"bluray": {"name": "x"}, "ok": {"name": "Good", "cfg": {"rf": 30}}, "!!": {"name": "y"}, "empty": {"name": " "}},
                                            default_for={"dvd": "ok", "nonsense": "x"})
        self.assertEqual(list(m.presets), ["ok"])
        self.assertEqual(m.presets["ok"]["cfg"]["quality"]["crf"], 30)
        self.assertEqual(m.default_for, {"dvd": "ok"})

    def test_prediction_with_machines(self):
        from app.state import peers_state
        peers_state.clear()
        peers_state.update({"secondtux": OLD, "maintux": NEW})
        try:
            cfg = clean_v2({"v": 2, "video": {"codec": "x264"}, "quality": {"crf": 18}})
            r = convert_presets.api_estimate(convert_presets.CfgReq(cfg=cfg))
            by = {n["name"]: n for n in r["nodes"]}
            self.assertTrue(by["maintux"]["ok"])
            self.assertFalse(by["secondtux"]["ok"])
            self.assertIn("older version", by["secondtux"]["reason"])
            self.assertLess(by["maintux"]["secs"], by["secondtux"]["secs"])
            self.assertTrue(r["example"])
            self.assertTrue(0 < r["out_bytes"] < r["in_bytes"])
        finally:
            peers_state.clear()


if __name__ == "__main__":
    unittest.main()
