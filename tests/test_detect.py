"""Tests für app/media/detect.py"""
import unittest

from app.media import detect as d

WD = [2652, 2620, 2695, 2601, 2648]                 # Episoden der Beispiel-Disc „The Walking Dead – Disc 1“


def twd_files(with_playall=True, sidecar=False):
    files = [{"path": f"The Walking Dead - Disc 1/The Walking Dead - Disc 1 - Titel {i + 1:02d}.mkv", "dur": s, "size": 7e9} for i, s in enumerate(WD)]
    if with_playall:
        files.append({"path": "The Walking Dead - Disc 1/The Walking Dead - Disc 1 - Titel 06.mkv", "dur": sum(WD[:4]), "size": 28e9})
    if sidecar:
        disc = {"name": "The Walking Dead - Disc 1", "volume": "THE_WALKING_DEAD_S1_D1",
                "titles": [{"id": i, "duration": f["dur"]} for i, f in enumerate(files)]}
        for i, f in enumerate(files):
            f["disc"], f["title_id"] = disc, i
    return files


class AnalyzeTest(unittest.TestCase):
    def test_label(self):
        a = d.analyze_name("WALKING_DEAD_S1_D1")
        self.assertEqual((a["title"], a["season"], a["disc"]), ("Walking Dead", 1, 1))

    def test_filename(self):
        a = d.analyze_name("The.Matrix.1999.1080p.BluRay.x264.mkv")
        self.assertEqual((a["title"], a["year"]), ("The Matrix", 1999))

    def test_future_year_is_title(self):
        a = d.analyze_name("BLADE_RUNNER_2049")
        self.assertEqual((a["title"], a["year"]), ("Blade Runner 2049", None))

    def test_title_number(self):
        a = d.analyze_name("The Walking Dead - Disc 1 - Titel 06.mkv")
        self.assertEqual((a["title"], a["disc"], a["title_no"]), ("The Walking Dead", 1, 6))
        self.assertEqual(d.analyze_name("2012")["title"], "2012")


class PlayAllTest(unittest.TestCase):
    def test_found(self):
        r = d.find_playall(WD + [sum(WD[:4])])
        self.assertEqual(r, {5: [0, 1, 2, 3]})

    def test_all_five(self):
        self.assertEqual(d.find_playall([2600, 2650, 2700, sum([2600, 2650, 2700])]), {3: [0, 1, 2]})

    def test_none(self):
        self.assertEqual(d.find_playall(WD), {})
        self.assertEqual(d.find_playall([7200, 600, 300]), {})

    def test_tolerance(self):
        self.assertEqual(list(d.find_playall([2600, 2650, 2600 + 2650 + 40]).keys()), [2])
        self.assertEqual(d.find_playall([2600, 2650, 2600 + 2650 + 400]), {})


class DetectTest(unittest.TestCase):
    def test_series_with_playall(self):
        r = d.detect(twd_files())
        self.assertEqual((r["kind"], r["title"], r["season"], r["disc"]), ("series", "The Walking Dead", 1, 1))
        self.assertGreaterEqual(r["confidence"], 0.85)
        roles = [i["role"] for i in r["items"]]
        self.assertEqual(roles, ["episode"] * 5 + ["playall"])
        self.assertEqual(r["items"][5]["playall_of"], [0, 1, 2, 3])

    def test_series_with_sidecar_selection_of_three(self):
        files = twd_files(sidecar=True)
        sel = [files[0], files[1], files[5]]                 # nur zwei Folgen und der Play-All gewählt
        r = d.detect(sel)
        self.assertEqual([i["role"] for i in r["items"]], ["episode", "episode", "playall"])
        self.assertEqual(r["title"], "The Walking Dead")

    def test_movie_with_extra(self):
        files = [{"path": "BLADE_RUNNER_2049/BLADE_RUNNER_2049_t00.mkv", "dur": 9788, "size": 30e9},
                 {"path": "BLADE_RUNNER_2049/BLADE_RUNNER_2049_t01.mkv", "dur": 600, "size": 1e9}]
        r = d.detect(files)
        self.assertEqual((r["kind"], r["title"]), ("movie", "Blade Runner 2049"))
        self.assertEqual([i["role"] for i in r["items"]], ["movie", "extra"])
        self.assertLess(r["confidence"], 0.8)                 # kein Jahr im Namen

    def test_movie_with_year_is_more_certain(self):
        r = d.detect([{"path": "Beispielfilm (2019)/Beispielfilm (2019).mkv", "dur": 7200, "size": 1}])
        self.assertEqual((r["kind"], r["title"], r["year"]), ("movie", "Beispielfilm", 2019))
        self.assertGreaterEqual(r["confidence"], 0.8)

    def test_unknown_without_durations(self):
        r = d.detect([{"path": "x/irgendwas.mkv", "dur": 0, "size": 1}])
        self.assertEqual(r["kind"], "unknown")
        r = d.detect([{"path": "Show/Show.S02E05.mkv", "dur": 0, "size": 1}])
        self.assertEqual(r["kind"], "series")

    def test_empty(self):
        self.assertEqual(d.detect([])["kind"], "unknown")


class EpisodesTest(unittest.TestCase):
    def test_numbers_and_tmdb(self):
        r = d.detect(twd_files())
        tm = [{"n": i + 1, "name": f"Folge {i + 1}", "runtime": 44} for i in range(10)]
        a = d.assign_episodes(r["items"], 1, 1, tm)
        self.assertEqual([x["episodes"] for x in a], [[1], [2], [3], [4], [5]])
        self.assertEqual(a[0]["name"], "Folge 1")
        self.assertIsNotNone(a[0]["delta"])

    def test_continue_on_disc2(self):
        r = d.detect(twd_files())
        a = d.assign_episodes(r["items"], 1, 6)
        self.assertEqual(a[0]["episodes"], [6])
        self.assertIsNone(a[0]["delta"])

    def test_double_episode(self):
        items = [{"path": "a", "role": "episode", "dur": 88 * 60}, {"path": "b", "role": "episode", "dur": 44 * 60}]
        tm = [{"n": i, "name": f"E{i}", "runtime": 44} for i in range(1, 6)]
        a = d.assign_episodes(items, 2, 1, tm)
        self.assertEqual([x["episodes"] for x in a], [[1, 2], [3]])


if __name__ == "__main__":
    unittest.main()
