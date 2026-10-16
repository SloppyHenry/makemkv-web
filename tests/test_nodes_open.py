"""Optional pairing, always discoverable: defaults, adding directly, hello."""
import asyncio
import unittest
from unittest import mock

from fastapi import HTTPException

from tests import env  # noqa: F401
from app import nodes, nodes_scan, nodes_store as store, state

NEU = {"ok": True, "ms": 1, "id": "abc", "name": "tux", "version": "0.4.0", "legacy": False, "mode": "verbund", "self": False}


class OpenPairingTest(unittest.TestCase):
    def setUp(self):
        self._old = dict(state.settings.get("nodes") or {})
        state.settings.pop("nodes", None)
        store.data.update({"nodes": [], "id": "me", "env_seen": []})
        self._save = mock.patch.object(store, "save")
        self._save.start()

    def tearDown(self):
        self._save.stop()
        state.settings["nodes"] = self._old

    def _add(self, url="http://10.0.0.5:8780"):
        with mock.patch.object(nodes, "probe_url", mock.AsyncMock(return_value=NEU)):
            return asyncio.run(nodes.api_add(nodes.UrlReq(url=url)))

    def test_standard_verbund_ohne_kopplungspflicht(self):
        c = store.cfg()
        self.assertEqual((c["mode"], c["pairing_required"]), ("verbund", False))
        self.assertEqual(nodes.NodesSettings().model_dump()["mode"], "verbund")
        self.assertFalse(nodes.NodesSettings().pairing_required)

    def test_neue_version_direkt_hinzufuegbar(self):
        n = self._add()
        self.assertEqual((n["name"], n["paired"], n["trust"]), ("tux", False, "legacy"))

    def test_mit_pflicht_nur_per_kopplung(self):
        state.settings["nodes"] = {"pairing_required": True}
        with self.assertRaises(HTTPException) as ctx:
            self._add()
        self.assertEqual(ctx.exception.status_code, 409)

    def test_hello_immer_im_verbund_nie_eigenstaendig(self):
        self.assertEqual(nodes_scan.hello()["app"], "spindle")
        state.settings["nodes"] = {"mode": "standalone"}
        with self.assertRaises(HTTPException) as ctx:
            nodes_scan.hello()
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
