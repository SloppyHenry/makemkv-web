"""Tests für app/media/auto.py (Entscheidung, ob automatisch einsortiert werden darf)."""
import unittest

from app.media import auto

CH = {"tmdb": 1402, "title": "The Walking Dead", "year": 2010, "imdb": "tt1520211", "poster": "/p.jpg"}


def res(conf=0.96, sim=1.0, kind="series", est=False, deltas=(0.1, -0.5), roles=("episode", "episode", "playall")):
    items = [{"path": f"d/{i}.mkv", "role": r, "dur": 2600} for i, r in enumerate(roles)]
    assigned = [{"path": f"d/{i}.mkv", "season": 1, "episodes": [i + 1], "name": f"E{i + 1}", "delta": d} for i, d in enumerate(deltas)]
    return {"detect": {"kind": kind, "confidence": conf, "season": 1, "disc": 1, "items": items},
            "tmdb": {"chosen": CH, "similarity": sim}, "start": {"estimated": est},
            "episodes": {"assigned": assigned, "error": ""}}


class AutoTest(unittest.TestCase):
    def test_ok(self):
        r = auto.build_request(res())
        self.assertEqual(r["kind"], "series")
        self.assertEqual([i["role"] for i in r["items"]], ["episode", "episode", "skip"])
        self.assertTrue(r["auto"])

    def test_refusals(self):
        self.assertIsNone(auto.build_request(res(conf=0.9)))
        self.assertIsNone(auto.build_request(res(sim=0.7)))
        self.assertIsNone(auto.build_request(res(est=True)))
        self.assertIsNone(auto.build_request(res(deltas=(0.1, 12))))
        self.assertIsNone(auto.build_request(res(deltas=(0.1, None))))
        r = res()
        r["tmdb"]["chosen"] = None
        self.assertIsNone(auto.build_request(r))

    def test_movie(self):
        r = res(kind="movie", roles=("movie", "extra"))
        q = auto.build_request(r)
        self.assertEqual([i["role"] for i in q["items"]], ["movie", "skip"])
        self.assertIsNone(auto.build_request(res(kind="movie", roles=("movie", "movie"))))


if __name__ == "__main__":
    unittest.main()
