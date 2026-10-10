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


if __name__ == "__main__":
    unittest.main()
