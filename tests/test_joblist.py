"""Tidying up the job list: only finished entries can be removed, running ones cannot."""
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

    async def test_finished_entry_is_removed(self):
        _setup()
        self.assertEqual(await joblist.api_conv_dismiss(3), {"ok": True})
        self.assertNotIn(3, [c["id"] for c in conversions])
        await joblist.api_upload_dismiss(1)
        self.assertNotIn(1, [u["id"] for u in uploads])

    async def test_running_or_waiting_entry_stays(self):
        _setup()
        for cid in (2, 6):
            with self.assertRaises(HTTPException) as e:
                await joblist.api_conv_dismiss(cid)
            self.assertEqual(e.exception.status_code, 409)
        for uid in (2, 3):     # "retry" is still being attempted
            with self.assertRaises(HTTPException) as e:
                await joblist.api_upload_dismiss(uid)
            self.assertEqual(e.exception.status_code, 409)
        self.assertEqual(len(conversions), 6)
        self.assertEqual(len(uploads), 4)

    async def test_unknown_entry_gives_404(self):
        _setup()
        with self.assertRaises(HTTPException) as e:
            await joblist.api_conv_dismiss(99)
        self.assertEqual(e.exception.status_code, 404)

    async def test_remove_all_finished(self):
        _setup()
        r = await joblist.api_dismiss_finished()
        self.assertEqual(r["removed"], 6)    # 4 conversions (done, cancelled, skipped, error) + 2 transfers (done, error)
        self.assertEqual([c["id"] for c in conversions], [2, 6])
        self.assertEqual([u["id"] for u in uploads], [2, 3])


if __name__ == "__main__":
    unittest.main()
