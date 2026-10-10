"""Übergabe an andere Rechner: neue Einstellungen gehen nur an Rechner, die sie verstehen; alte bekommen die fünf Felder."""
import copy
import unittest

from tests import env  # noqa: F401
from app import cluster
from app.convert_schema import SCHEMA, clean_v2, default_v2

ALT = {"reachable": True, "legacy": True, "has_handover": True, "capabilities": {}}
NEU = {"reachable": True, "legacy": False, "has_handover": True,
       "capabilities": {"convert": {"schema": SCHEMA, "codecs": ["x265", "x264", "svtav1"], "hw": [], "filters": [], "audio": ["copy", "aac", "ac3", "eac3", "opus"]}}}


class CfgForPeerTest(unittest.TestCase):
    def test_standard_geht_an_alten_rechner_als_fuenf_felder(self):
        cfg, why = cluster.cfg_for_peer(clean_v2(default_v2()), ALT)
        self.assertEqual(why, "")
        self.assertEqual(set(cfg), {"convert", "rf", "preset", "tune", "extra", "audio"})

    def test_angepasster_auftrag_geht_nicht_an_alten_rechner(self):
        d = copy.deepcopy(clean_v2(default_v2()))
        d["video"]["codec"] = "x264"
        d["video"]["bits"] = 8
        cfg, why = cluster.cfg_for_peer(clean_v2(d), ALT)
        self.assertIsNone(cfg)
        self.assertIn("älterer Stand", why)

    def test_neuer_rechner_bekommt_alles(self):
        d = clean_v2(default_v2())
        cfg, why = cluster.cfg_for_peer(d, NEU)
        self.assertEqual((cfg, why), (d, ""))

    def test_nicht_erreichbar_und_unbekannt(self):
        d = clean_v2(default_v2())
        self.assertIsNone(cluster.cfg_for_peer(d, {**NEU, "reachable": False})[0])
        self.assertIsNone(cluster.cfg_for_peer(d, None)[0])


class StartAnPeerTest(unittest.IsolatedAsyncioTestCase):
    """Regression: /api/convert/start rief die async peer_call über to_thread auf und gab eine Coroutine zurück (500)."""

    async def test_start_auf_anderem_rechner_wartet_den_aufruf_ab(self):
        from unittest import mock
        from app import convert_presets, state
        gesendet = {}

        async def fake_peer_call(name, path, body, timeout=15.0):
            gesendet.update(name=name, path=path, body=body)
            return {"started": body["paths"], "skipped": []}

        state.peers_state["alt"] = {**ALT, "name": "alt"}
        try:
            with mock.patch.object(cluster, "peer_call", fake_peer_call):
                r = await convert_presets.api_start(convert_presets.StartReq(target="alt", paths=["a/b.mkv"], convert={"rf": 20}))
        finally:
            state.peers_state.pop("alt", None)
        self.assertEqual(r["started"], ["a/b.mkv"])
        self.assertEqual((gesendet["name"], gesendet["path"]), ("alt", "library/convert"))
        self.assertEqual(set(gesendet["body"]["convert"]), {"convert", "rf", "preset", "tune", "extra", "audio"})


if __name__ == "__main__":
    unittest.main()
