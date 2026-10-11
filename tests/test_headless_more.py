"""Tests für TMDB-Laufzeitabgleich, Gedächtnis, Titelwahl-Reihenfolge und Meldung an TheDiscDB."""
import asyncio
import json
import unittest
from unittest import mock

from tests import env  # noqa: F401
from tests.test_headless import T

from app.headless import choose, contribute, memory, plan, tmdbmatch
from app.state import settings


class FakeDrive:
    def __init__(self, disc, dev="/dev/srX"):
        self.dev, self.disc, self.scan_id, self.scan_raw = dev, disc, 1, ['TCOUNT:2', 'TINFO:0,9,0,"1:58:00"']


class TmdbMatchTest(unittest.TestCase):
    def test_movie_runtime_picks_one(self):
        disc = {"type": "Blu-ray disc", "name": "DER_FILM", "titles": [T(0, 7080, 30), T(1, 5400, 10), T(2, 600, 1)]}
        r = tmdbmatch.match({"kind": "movie", "title": "Der Film", "year": 2001, "runtime": 118}, choose.prepare(disc), disc)
        self.assertEqual((r["ok"], r["picks"], r["folder"]), (True, [0], "Der Film (2001)"))

    def test_movie_runtime_ambiguous(self):
        disc = {"type": "Blu-ray disc", "name": "X", "titles": [T(0, 7080, 30, segments="1"), T(1, 7140, 31, segments="2")]}
        r = tmdbmatch.match({"kind": "movie", "title": "X", "year": None, "runtime": 118}, choose.prepare(disc), disc)
        self.assertFalse(r["ok"])

    def test_long_episodes_by_tmdb(self):
        disc = {"type": "Blu-ray disc", "name": "SHERLOCK_S1_D1", "titles": [T(0, 5280, 20), T(1, 5340, 20), T(2, 5300, 20), T(3, 1200, 2)]}
        self.assertEqual(choose.decide(disc, 45e9)["mode"], "unsure")
        r = tmdbmatch.match({"kind": "series", "title": "Sherlock", "year": 2010, "season": 1, "episodes": [88, 89, 89]}, choose.prepare(disc), disc)
        self.assertEqual((r["ok"], sorted(r["picks"]), r["folder"]), (True, [0, 1, 2], "Sherlock (2010) - Staffel 1 Disc 1"))

    def test_lookup_needs_unique_kind(self):
        async def search(key, kind, q, year=None, lang=""):
            return [{"title": "Dune", "original": "Dune", "tmdb": 1 if kind == "movie" else 2, "year": 2021}]
        with mock.patch("app.media.conf.cfg", return_value={"tmdb_key": "k", "language": "de-DE"}), \
                mock.patch("app.media.metadata.search", search):
            self.assertIsNone(asyncio.run(tmdbmatch.lookup({"name": "DUNE"})))


class MemoryTest(unittest.TestCase):
    def setUp(self):
        memory._entries.clear()
        memory._loaded[0] = True

    def test_record_and_match_other_title_ids(self):
        ids = {"disc_id": "A" * 40, "content_hash": "B" * 32}
        disc = {"type": "Blu-ray disc", "name": "FILM", "titles": [T(0, 7080, 30, source="00800.mpls"), T(1, 600, 1, source="00010.mpls")]}
        memory.record(ids, disc, disc["titles"][0], "Mein Film (2001)", "Mein Film (2001)")
        self.assertEqual(memory.count(), 1)
        later = {"type": "Blu-ray disc", "titles": [T(0, 30, 0.01, source="00001.mpls"), T(1, 600, 1, source="00010.mpls"), T(2, 7080, 30, source="00800.mpls")]}
        m = memory.match(memory.find_local("A" * 40, ""), later)
        self.assertEqual((m["ok"], m["picks"], m["names"], m["folder"]), (True, [2], {2: "Mein Film (2001)"}, "Mein Film (2001)"))

    def test_plan_prefers_memory(self):
        ids = {"disc_id": "", "content_hash": "C" * 32, "content_bytes": 40e9}
        disc = {"type": "DVD disc", "name": "SERIE", "titles": [T(0, 1300, byt=900_000_111), T(1, 1310, byt=900_000_222), T(2, 2610, byt=1_800_000_333)]}
        memory.record(ids, disc, disc["titles"][1], "Serie S01E02", "Serie Staffel 1")
        dr = FakeDrive(disc)
        with mock.patch.object(plan, "get_ids", mock.AsyncMock(return_value=ids)), mock.patch.object(plan.discdb, "lookup") as db:
            p = asyncio.run(plan.plan(dr))
        db.assert_not_called()
        self.assertEqual((p["mode"], p["picks"], p["names"][1], p["folder"]), ("memory", [1], "Serie S01E02", "Serie Staffel 1"))

    def test_plan_falls_through_to_tmdb_then_structure(self):
        settings.setdefault("headless", {})["use_db"] = True
        ids = {"disc_id": "", "content_hash": "D" * 32, "content_bytes": 40e9}
        disc = {"type": "Blu-ray disc", "name": "DER_FILM", "titles": [T(0, 7080, 30), T(1, 8400, 30), T(2, 600, 1)]}
        info = {"kind": "movie", "tmdb": 5, "title": "Der Film", "year": 2001, "runtime": 118, "season": None, "episodes": []}
        with mock.patch.object(plan, "get_ids", mock.AsyncMock(return_value=ids)), \
                mock.patch.object(plan.discdb, "lookup", mock.AsyncMock(return_value=(None, ""))), \
                mock.patch.object(plan.tmdbmatch, "lookup", mock.AsyncMock(return_value=info)):
            p = asyncio.run(plan.plan(FakeDrive(disc)))
        self.assertEqual((p["mode"], p["source"], p["picks"], p["names"]), ("movie", "TMDB (Laufzeit)", [0], {0: "Der Film (2001)"}))
        self.assertIn("Disc nicht in TheDiscDB", p["reasons"])
        with mock.patch.object(plan, "get_ids", mock.AsyncMock(return_value=ids)), \
                mock.patch.object(plan.discdb, "lookup", mock.AsyncMock(return_value=(None, ""))), \
                mock.patch.object(plan.tmdbmatch, "lookup", mock.AsyncMock(return_value=None)):
            p = asyncio.run(plan.plan(FakeDrive(disc)))
        self.assertEqual((p["mode"], p["source"]), ("unsure", "Struktur der Disc"))


class PeerMemoryTest(unittest.TestCase):
    def test_lookup_asks_peers_with_capability(self):
        memory._entries.clear()
        memory._loaded[0] = True
        calls = []

        async def peer_call(name, path, body=None, timeout=15):
            calls.append((name, path, body))
            return {"entry": {"content_hash": "F" * 32, "titles": [], "folder": "X"}}
        peers = {"alt": {"reachable": True, "capabilities": {}}, "aus": {"reachable": False, "capabilities": {"headless_memory": True}},
                 "neu": {"reachable": True, "capabilities": {"headless_memory": True}}}
        with mock.patch.dict(memory.peers_state, peers, clear=True), mock.patch("app.cluster.peer_call", peer_call):
            e, where = asyncio.run(memory.lookup({"content_hash": "F" * 32}))
        self.assertEqual((where, e["folder"], [c[0] for c in calls]), ("neu", "X", ["neu"]))
        self.assertEqual(calls[0][1:], ("headless/memory/lookup", {"disc_id": "", "content_hash": "F" * 32}))


class ContributeTest(unittest.TestCase):
    disc = {"type": "Blu-ray disc", "name": "FILM", "volume": "FILM_DE", "titles": [T(0, 7080, 30, source="00800.mpls", segments="1,2"), T(1, 600, 1, source="00010.mpls")]}
    ids = {"content_hash": "E" * 32, "disc_id": ""}

    def test_build_payload(self):
        req = contribute.ContribReq(kind="movie", tmdb_id=42, title="Film", upc="4 006680 012345",
                                    titles=[contribute.ContribTitle(id=0, type="MainMovie"), contribute.ContribTitle(id=1, type="Trailer")])
        p, log = contribute.build(self.disc, self.ids, ["TCOUNT:2"], req)
        self.assertEqual(p["disc"], {"content_hash": "E" * 32, "volume_label": "FILM_DE", "content_type": "blu-ray", "disc_number": None})
        self.assertEqual(p["identification"]["tmdb_id"], 42)
        self.assertIsNone(p["identification"]["detected_season"])
        self.assertEqual([(t["index"], t["title_type"], t["source_filename"], t["segment_count"]) for t in p["titles"]],
                         [(0, "MainMovie", "00800.mpls", 2), (1, "Trailer", "00010.mpls", None)])
        self.assertEqual((p["upc"], log), ("4006680012345", "TCOUNT:2\n"))

    def test_build_checks(self):
        with self.assertRaises(contribute.ContribError):
            contribute.build(self.disc, self.ids, [], contribute.ContribReq(kind="movie", titles=[contribute.ContribTitle(id=1, type="Extra")]))
        with self.assertRaises(contribute.ContribError):
            contribute.build(self.disc, {}, [], contribute.ContribReq(kind="movie", titles=[contribute.ContribTitle(id=0, type="MainMovie")]))
        req = contribute.ContribReq(kind="series", season=2, titles=[contribute.ContribTitle(id=0, type="Episode", episode="3")])
        p, _ = contribute.build(self.disc, self.ids, [], req)
        self.assertEqual((p["identification"]["detected_season"], p["titles"][0]["season"], p["titles"][0]["episode"]), (2, "2", "3"))

    def test_submit_posts_disc_then_log(self):
        calls = []

        def post(url, data, ctype, timeout=30):
            calls.append((url.split("/api/")[1], ctype))
            return 200, json.dumps({"id": 1, "updated": False}).encode()
        p, log = contribute.build(self.disc, self.ids, ["TCOUNT:2"], contribute.ContribReq(titles=[contribute.ContribTitle(id=0, type="MainMovie")]))
        with mock.patch.object(contribute, "_post", post):
            r = asyncio.run(contribute.submit(p, log))
        self.assertEqual(r, {"ok": True, "updated": False, "log": True})
        self.assertEqual(calls, [("engram/disc", "application/json"), (f"engram/disc/{'E' * 32}/logs/scan", "text/plain")])

    def test_types_from_names(self):
        t = contribute._types_from_names([0, 1], {0: "Serie S01E04", 1: "Bonus"}, self.disc)
        self.assertEqual((t[0]["type"], t[0]["episode"], t[1]["type"]), ("Episode", "4", "Extra"))


if __name__ == "__main__":
    unittest.main()
