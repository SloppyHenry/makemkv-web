"""Tests für app/media/naming.py (reine Funktionen). Aufruf: python -m unittest discover -s tests"""
import unittest

from app.media import naming as n


class CleanTest(unittest.TestCase):
    def test_illegal_chars(self):
        self.assertEqual(n.clean_part("Star Trek: Voyager"), "Star Trek - Voyager")
        self.assertEqual(n.clean_part("Wer hat Angst vor Virginia Woolf?"), "Wer hat Angst vor Virginia Woolf")
        self.assertEqual(n.clean_part('Er sagte "Hallo" <b>*'), "Er sagte 'Hallo' b")
        self.assertEqual(n.clean_part("AC/DC | Live"), "AC - DC - Live")
        self.assertEqual(n.clean_part("A:B"), "A - B")

    def test_umlauts_kept_and_trailing_dots(self):
        self.assertEqual(n.clean_part("Tschüß Fußball.  "), "Tschüß Fußball")
        self.assertEqual(n.clean_part("Ärger & Übung – Größe"), "Ärger & Übung – Größe")
        self.assertEqual(n.clean_part("Mr. Robot"), "Mr. Robot")

    def test_empty_and_long(self):
        self.assertEqual(n.clean_part("   "), "")
        self.assertLessEqual(len(n.clean_part("x" * 500)), 120)


class IdTagTest(unittest.TestCase):
    def test_prefer(self):
        self.assertEqual(n.id_tag("tt1856101", 335984), "[imdbid-tt1856101]")
        self.assertEqual(n.id_tag("tt1856101", 335984, "tmdb"), "[tmdbid-335984]")
        self.assertEqual(n.id_tag(None, 1402), "[tmdbid-1402]")
        self.assertEqual(n.id_tag("kaputt", None), "")
        self.assertEqual(n.id_tag(), "")


class MovieTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(n.movie_rel("Blade Runner 2049", 2017, ".mkv", imdb="tt1856101"),
                         "Blade Runner 2049 (2017) [imdbid-tt1856101]/Blade Runner 2049 (2017) [imdbid-tt1856101].mkv")

    def test_no_tags_no_year(self):
        self.assertEqual(n.movie_rel("Film", None, ".mkv", imdb="tt1234567", tags=False), "Film/Film.mkv")

    def test_version_and_extra(self):
        self.assertEqual(n.movie_rel("Film", 2021, ".mkv", version="1080p"), "Film (2021)/Film (2021) - 1080p.mkv")
        self.assertEqual(n.movie_rel("Film", 2021, ".mkv", extra="behind the scenes", extra_name="Die Musik"),
                         "Film (2021)/behind the scenes/Die Musik.mkv")
        self.assertEqual(n.movie_rel("Film", 2021, ".mkv", extra="unbekannt", extra_name="X"), "Film (2021)/extras/X.mkv")


class SeriesTest(unittest.TestCase):
    def test_episode(self):
        self.assertEqual(n.episode_rel("The Walking Dead", 2010, 1, [1], ".mkv", tmdb=1402),
                         "The Walking Dead (2010) [tmdbid-1402]/Season 01/The Walking Dead S01E01.mkv")

    def test_double_and_names_and_special(self):
        self.assertEqual(n.episode_rel("Serie", 2020, 2, [3, 4], ".mkv", ep_name="Teil: 1"), "Serie (2020)/Season 02/Serie S02E03-E04 - Teil - 1.mkv")
        self.assertEqual(n.episode_rel("Serie", None, 0, [1], ".mkv"), "Serie/Season 00/Serie S00E01.mkv")

    def test_gap_rejected(self):
        with self.assertRaises(ValueError):
            n.episode_code(1, [1, 3])
        with self.assertRaises(ValueError):
            n.episode_code(1, [])

    def test_series_extra(self):
        self.assertEqual(n.series_extra_rel("Serie", 2020, 1, ".mkv", tmdb=5, extra_name="Play All"), "Serie (2020) [tmdbid-5]/extras/Play All.mkv")

    def test_unique_variant(self):
        self.assertEqual(n.unique_variant("a/b/Serie S01E03.mkv", 2), "a/b/Serie S01E03 - 2.mkv")


class ParseTest(unittest.TestCase):
    def test_series_path(self):
        r = n.parse_path("The Walking Dead (2010) [tmdbid-1402]/Season 01/The Walking Dead S01E02-E03 - Guts.mkv")
        self.assertEqual((r["kind"], r["title"], r["year"], r["tag"], r["id"], r["season"], r["episode"], r["episode_end"]),
                         ("series", "The Walking Dead", 2010, "tmdbid", "1402", 1, 2, 3))

    def test_loose_episode(self):
        r = n.parse_path("Downloads/Show.Name.S03E07.1080p.mkv")
        self.assertEqual((r["kind"], r["title"], r["season"], r["episode"]), ("series", "Show Name", 3, 7))

    def test_movie_path(self):
        r = n.parse_path("Blade Runner 2049 (2017) [imdbid-tt1856101]/Blade Runner 2049 (2017) [imdbid-tt1856101].mkv")
        self.assertEqual((r["kind"], r["title"], r["year"], r["id"], r["extra"]), ("movie", "Blade Runner 2049", 2017, "tt1856101", False))
        r = n.parse_path("Film (2021)/featurettes/Making of.mkv")
        self.assertEqual((r["kind"], r["title"], r["extra"]), ("movie", "Film", True))

    def test_unknown(self):
        self.assertEqual(n.parse_path("The Walking Dead - Disc 1/The Walking Dead - Disc 1 - Titel 01.mkv"), {})
        self.assertEqual(n.parse_path(""), {})


if __name__ == "__main__":
    unittest.main()
