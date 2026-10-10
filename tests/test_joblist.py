"""Auftragsliste aufräumen: nur beendete Einträge lassen sich entfernen, laufende nicht."""
import unittest

from fastapi import HTTPException

from tests import env  # noqa: F401
from app import joblist
from app.state import conversions, uploads


def _setup():
    conversions[:] = [{"id": 1, "status": "done"}, {"id": 2, "status": "running"}, {"id": 3, "status": "cancelled"},
                      {"id": 4, "status": "skipped"}, {"id": 5, "status": "error"}, {"id": 6, "status": "queued"}]
    uploads[:] = [{"id": 1, "status": "done"}, {"id": 2, "status": "copying"}, {"id": 3, "status": "retry"}, {"id": 4, "status": "error"}]


class DismissTest(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        conversions.clear()
        uploads.clear()

    async def test_beendeter_eintrag_wird_entfernt(self):
        _setup()
        self.assertEqual(await joblist.api_conv_dismiss(3), {"ok": True})
        self.assertNotIn(3, [c["id"] for c in conversions])
        await joblist.api_upload_dismiss(1)
        self.assertNotIn(1, [u["id"] for u in uploads])

    async def test_laufender_oder_wartender_eintrag_bleibt(self):
        _setup()
        for cid in (2, 6):
            with self.assertRaises(HTTPException) as e:
                await joblist.api_conv_dismiss(cid)
            self.assertEqual(e.exception.status_code, 409)
        for uid in (2, 3):     # „retry“ wird noch versucht
            with self.assertRaises(HTTPException) as e:
                await joblist.api_upload_dismiss(uid)
            self.assertEqual(e.exception.status_code, 409)
        self.assertEqual(len(conversions), 6)
        self.assertEqual(len(uploads), 4)

    async def test_unbekannter_eintrag_gibt_404(self):
        _setup()
        with self.assertRaises(HTTPException) as e:
            await joblist.api_conv_dismiss(99)
        self.assertEqual(e.exception.status_code, 404)

    async def test_alle_beendeten_entfernen(self):
        _setup()
        r = await joblist.api_dismiss_finished()
        self.assertEqual(r["removed"], 6)    # 4 Konvertierungen (fertig, abgebrochen, übersprungen, Fehler) + 2 Übertragungen (fertig, Fehler)
        self.assertEqual([c["id"] for c in conversions], [2, 6])
        self.assertEqual([u["id"] for u in uploads], [2, 3])


if __name__ == "__main__":
    unittest.main()
