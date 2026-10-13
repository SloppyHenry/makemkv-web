"""Hand-over to other machines: new settings only go to machines that understand them; old ones get the five fields."""
import copy
import unittest

from tests import env  # noqa: F401
from app import cluster
from app.convert_schema import SCHEMA, clean_v2, default_v2

OLD = {"reachable": True, "legacy": True, "has_handover": True, "capabilities": {}}
NEW = {"reachable": True, "legacy": False, "has_handover": True,
       "capabilities": {"convert": {"schema": SCHEMA, "codecs": ["x265", "x264", "svtav1"], "hw": [], "filters": [], "audio": ["copy", "aac", "ac3", "eac3", "opus"]}}}


class CfgForPeerTest(unittest.TestCase):
    def test_default_goes_to_old_machine_as_five_fields(self):
        cfg, why = cluster.cfg_for_peer(clean_v2(default_v2()), OLD)
        self.assertEqual(why, "")
        self.assertEqual(set(cfg), {"convert", "rf", "preset", "tune", "extra", "audio"})

    def test_adjusted_job_does_not_go_to_old_machine(self):
        d = copy.deepcopy(clean_v2(default_v2()))
        d["video"]["codec"] = "x264"
        d["video"]["bits"] = 8
        cfg, why = cluster.cfg_for_peer(clean_v2(d), OLD)
        self.assertIsNone(cfg)
        self.assertIn("older version", why)

    def test_new_machine_gets_everything(self):
        d = clean_v2(default_v2())
        cfg, why = cluster.cfg_for_peer(d, NEW)
        self.assertEqual((cfg, why), (d, ""))

    def test_unreachable_and_unknown(self):
        d = clean_v2(default_v2())
        self.assertIsNone(cluster.cfg_for_peer(d, {**NEW, "reachable": False})[0])
        self.assertIsNone(cluster.cfg_for_peer(d, None)[0])


class StartOnPeerTest(unittest.IsolatedAsyncioTestCase):
    """Regression: /api/convert/start called the async peer_call via to_thread and returned a coroutine (500)."""

    async def test_start_on_another_machine_awaits_the_call(self):
        from unittest import mock
        from app import convert_presets, state
        sent = {}

        async def fake_peer_call(name, path, body, timeout=15.0):
            sent.update(name=name, path=path, body=body)
            return {"started": body["paths"], "skipped": []}

        state.peers_state["old"] = {**OLD, "name": "old"}
        try:
            with mock.patch.object(cluster, "peer_call", fake_peer_call):
                r = await convert_presets.api_start(convert_presets.StartReq(target="old", paths=["a/b.mkv"], convert={"rf": 20}))
        finally:
            state.peers_state.pop("old", None)
        self.assertEqual(r["started"], ["a/b.mkv"])
        self.assertEqual((sent["name"], sent["path"]), ("old", "library/convert"))
        self.assertEqual(set(sent["body"]["convert"]), {"convert", "rf", "preset", "tune", "extra", "audio"})


if __name__ == "__main__":
    unittest.main()
