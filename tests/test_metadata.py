"""Tests für app/media/metadata.py gegen die lokale TMDB-Attrappe (scripts/tmdb_mock.py), kein Netzwerkzugriff nach außen."""
import asyncio
import importlib.util
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from app.media import metadata as m
from app.media import store

spec = importlib.util.spec_from_file_location("tmdb_mock", Path(__file__).resolve().parent.parent / "scripts" / "tmdb_mock.py")
mock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mock)
run = asyncio.run


class MetadataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), mock.H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.tmp = tempfile.TemporaryDirectory()
        store.DATA = Path(cls.tmp.name)
        m.BASE = f"http://127.0.0.1:{cls.srv.server_address[1]}/3"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.tmp.cleanup()

    def setUp(self):
        store.reset_memory()
        self.calls = 0
        orig = m._http_get

        def counting(*a, **k):
            self.calls += 1
            return orig(*a, **k)
        m._http_get = counting
        self.addCleanup(setattr, m, "_http_get", orig)

    def test_no_key(self):
        with self.assertRaises(m.MetadataError) as c:
            run(m.search("", "tv", "walking"))
        self.assertEqual(c.exception.code, "no_key")
        self.assertEqual(self.calls, 0)

    def test_key_test(self):
        self.assertTrue(run(m.test_key("testkey"))["ok"])
        bad = run(m.test_key("falsch"))
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["code"], "bad_key")

    def test_search_and_cache(self):
        r = run(m.search("testkey", "tv", "walking dead"))
        self.assertEqual([x["tmdb"] for x in r], [1402, 94305])
        self.assertEqual(r[0]["year"], 2010)
        self.assertTrue(r[0]["poster_url"].endswith("/w185/twd.jpg"))
        n = self.calls
        run(m.search("testkey", "tv", "walking dead"))
        self.assertEqual(self.calls, n)                                  # aus dem Zwischenspeicher
        self.assertGreater(m.cache_size(), 0)

    def test_year_filter(self):
        r = run(m.search("testkey", "movie", "blade runner", 1982))
        self.assertEqual([x["tmdb"] for x in r], [78])

    def test_details_imdb(self):
        d = run(m.details("testkey", "tv", 1402))
        self.assertEqual((d["imdb"], d["runtime"], d["seasons"]), ("tt1520211", 44, [0, 1, 2]))
        self.assertEqual(run(m.details("testkey", "movie", 335984))["imdb"], "tt1856101")

    def test_find(self):
        r = run(m.find_imdb("testkey", "tt1520211"))
        self.assertEqual((r["kind"], r["tmdb"]), ("tv", 1402))
        self.assertEqual(run(m.find_imdb("testkey", "tt0133093"))["kind"], "movie")
        self.assertIsNone(run(m.find_imdb("testkey", "tt9999999")))
        with self.assertRaises(m.MetadataError):
            run(m.find_imdb("testkey", "1520211"))

    def test_season(self):
        eps = run(m.season("testkey", 1402, 1))
        self.assertEqual((eps[0]["n"], eps[0]["name"], eps[0]["runtime"]), (1, "Days Gone Bye", 45))
        with self.assertRaises(m.MetadataError) as c:
            run(m.season("testkey", 1402, 9))
        self.assertEqual(c.exception.code, "not_found")

    def test_network_error_uses_stale_cache(self):
        run(m.search("testkey", "movie", "matrix"))
        old = m.BASE
        m.BASE = "http://127.0.0.1:9/3"                                  # nichts hört zu
        try:
            self.assertEqual(run(m.search("testkey", "movie", "matrix", ))[0]["tmdb"], 603)   # frisch genug: Cache
            with self.assertRaises(m.MetadataError) as c:
                run(m.search("testkey", "movie", "nichtda"))
            self.assertEqual(c.exception.code, "network")
        finally:
            m.BASE = old


if __name__ == "__main__":
    unittest.main()
