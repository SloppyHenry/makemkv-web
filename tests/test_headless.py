"""Tests für den Headless-Modus: UDF-Leser, Disc-Kennungen, TheDiscDB-Zuordnung, Titelwahl ohne Datenbank."""
import asyncio
import hashlib
import json
import os
import tempfile
import unittest
from unittest import mock

from tests import env  # noqa: F401
from tests.udf_build import build

from app.headless import choose, discdb, discid, plan, udf

# echte Einträge aus TheDiscDB (Dateigrößen aus dem Scan-Protokoll, Hash aus disc01.json)
CLOVERFIELD = [(f"{n:05d}.m2ts", s) for n, s in [
    (0, 319488), (22, 22960128), (51, 26376192), (53, 26572800), (250, 2739793920), (800, 28558835712), (1007, 36249600), (1008, 36249600),
    (1009, 36249600), (1010, 106168320), (1011, 106168320), (1012, 233472), (1013, 301056), (1014, 301056), (1015, 331776), (1016, 288768),
    (1017, 196608), (1018, 436224), (1019, 337920), (1020, 307200), (1021, 325632), (1022, 307200), (1023, 528384), (1024, 356352), (1025, 301056),
    (1026, 270336), (1027, 282624), (1028, 282624), (1029, 307200), (1030, 307200), (1031, 393216), (1032, 307200), (1033, 276480), (1034, 288768),
    (1035, 301056), (1036, 294912), (1037, 251904), (1038, 301056), (1039, 307200), (1040, 215040), (1041, 337920), (1042, 313344), (1043, 307200),
    (1044, 196608), (1045, 313344), (1046, 319488), (1047, 301056), (1048, 270336), (1049, 319488), (1050, 301056), (1051, 313344), (1052, 374784),
    (1053, 282624), (1054, 319488), (1055, 301056), (1056, 301056), (1057, 970752), (1058, 288768), (1059, 270336), (1060, 190464), (1061, 190464),
    (1062, 147456), (1063, 423936), (1066, 1137014784), (1067, 516808704), (1068, 1830144000), (1069, 2006980608), (1070, 893718528), (1071, 970752),
    (1072, 970752), (1073, 1155606528)]]
BAKUGAN = [("VIDEO_TS.BUP", 14336), ("VIDEO_TS.VOB", 20480), ("VTS_01_0.BUP", 106496), ("VTS_01_0.IFO", 106496), ("VIDEO_TS.IFO", 14336),
           ("VTS_01_0.VOB", 11745280), ("VTS_01_1.VOB", 1073393664), ("VTS_01_4.VOB", 1073532928), ("VTS_01_5.VOB", 236564480),
           ("VTS_02_0.IFO", 18432), ("VTS_02_0.VOB", 20480), ("VTS_01_2.VOB", 1073551360), ("VTS_01_3.VOB", 1073661952),
           ("VTS_02_0.BUP", 18432), ("VTS_02_1.VOB", 16025600)]


def T(i, secs, gb=1.0, name="Disc", source="", segments="", byt=None):
    return {"id": i, "name": name, "duration": secs, "duration_text": f"{secs // 3600}:{secs % 3600 // 60:02d}:{secs % 60:02d}",
            "bytes": byt if byt is not None else int(gb * 1e9), "source": source, "segments": segments, "chapters": 1, "tracks": []}


class HashTest(unittest.TestCase):
    def test_content_hash_matches_thediscdb(self):
        self.assertEqual(discid.content_hash(CLOVERFIELD[::-1]), "57B059114B517DF43BE4D05FCA0869FA")
        self.assertEqual(discid.content_hash(BAKUGAN), "673AB3EBB0E4384CF398E248C0860F23")

    def test_dvd_disc_id(self):
        head = bytearray(4096)
        head[0x3F] = 2
        a, b, c = bytes(head), b"A" * 2048, b"B" * 2048
        self.assertEqual(discid.dvd_disc_id(a, [b, c, b"nicht"]), hashlib.md5(a + b + c).hexdigest().upper())
        self.assertEqual(discid.dvd_disc_id(a, [None, c]), hashlib.md5(a + c).hexdigest().upper())


class UdfTest(unittest.TestCase):
    def _identify(self, files, version):
        with tempfile.NamedTemporaryFile(suffix=".iso", delete=False) as f:
            f.write(build(files, version))
        try:
            fs, close = udf.open_device(f.name)
            try:
                return discid.identify(fs)
            finally:
                close()
        finally:
            os.unlink(f.name)

    def test_bluray_both_versions(self):
        uk = os.urandom(5000)
        files = {f"BDMV/STREAM/{n}": s for n, s in CLOVERFIELD[:12]}
        files.update({"AACS/Unit_Key_RO.inf": uk, "BDMV/index.bdmv": b"INDX0200", "BDMV/PLAYLIST/00800.mpls": 4000})
        for v in ("1.02", "2.50"):
            r = self._identify(files, v)
            self.assertEqual(r["format"], "bluray", v)
            self.assertEqual(r["content_hash"], discid.content_hash(CLOVERFIELD[:12]), v)
            self.assertEqual(r["disc_id"], hashlib.sha1(uk).hexdigest().upper(), v)
            self.assertEqual(r["content_bytes"], sum(s for _n, s in CLOVERFIELD[:12]), v)

    def test_dvd(self):
        head = bytearray(os.urandom(8192))
        head[0x3E], head[0x3F] = 0, 2
        v1, v2 = os.urandom(4096), os.urandom(2048)
        files = {f"VIDEO_TS/{n}": s for n, s in BAKUGAN if not n.endswith(".IFO")}
        files.update({"VIDEO_TS/VIDEO_TS.IFO": bytes(head), "VIDEO_TS/VTS_01_0.IFO": v1, "VIDEO_TS/VTS_02_0.IFO": v2})
        r = self._identify(files, "1.02")
        self.assertEqual(r["format"], "dvd")
        self.assertEqual(r["disc_id"], hashlib.md5(bytes(head) + v1 + v2).hexdigest().upper())
        self.assertEqual(r["files"], len(BAKUGAN))

    def test_not_udf(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"\0" * 600 * 2048)
        try:
            with self.assertRaises(udf.UdfError):
                udf.open_device(f.name)
        finally:
            os.unlink(f.name)


SERIES_ENTRY = {"format": "Blu-Ray", "media": {"title": "Mission: Impossible", "year": 1966, "type": "Series"}, "disc": {"name": "Season 1 Disc 1"},
                "titles": [{"source_file": "00203.mpls", "duration": "0:50:29", "size": 10973730816, "item": {"title": "Operation Rogosh", "type": "Episode", "season": "1", "episode": "3"}},
                           {"source_file": "00202.mpls", "duration": "0:50:29", "size": 11178485760, "item": {"title": "Memory", "type": "Episode", "season": "1", "episode": "2"}},
                           {"source_file": "00201.mpls", "duration": "0:50:30", "size": 11157866496, "item": {"title": "Pilot", "type": "Episode", "season": "1", "episode": "1"}},
                           {"source_file": "00389.mpls", "duration": "0:01:42", "size": 232089600}]}
DVD_ENTRY = {"format": "DVD", "media": {"title": "Bakugan Battle Brawlers", "year": 2007, "type": "Series"}, "disc": {"name": "DVD"},
             "titles": [{"source_file": "01", "segment_map": "1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20", "duration": "1:50:40", "size": 4515041280},
                        {"source_file": "02", "segment_map": "1,2,3,4", "duration": "0:22:08", "size": 902615040, "item": {"type": "Episode", "season": "1", "episode": "1", "title": "Bakugan: The Battle Begins"}},
                        {"source_file": "03", "segment_map": "1,2,3,4", "duration": "0:22:08", "size": 902762496, "item": {"type": "Episode", "season": "1", "episode": "2", "title": "Masquerade Ball"}}]}


class DiscDbTest(unittest.TestCase):
    def test_bluray_series_by_playlist(self):
        disc = {"type": "Blu-ray disc", "titles": [T(0, 3030, 11.1, source="00201.mpls"), T(1, 3029, 11.2, source="00202.mpls"),
                                                   T(2, 3029, 11.0, source="00203.mpls"), T(3, 3029, 11.0, source="00104.mpls")]}
        m = discdb.match(SERIES_ENTRY, disc)
        self.assertTrue(m["ok"], m["reason"])
        self.assertEqual(sorted((p["id"], p["episode"]) for p in m["picks"]), [(0, "1"), (1, "2"), (2, "3")])
        folder, names = plan.names_from_db(m)
        self.assertEqual(folder, "Mission - Impossible (1966) - Season 1 Disc 1")
        self.assertEqual(names[0], "Mission - Impossible S01E01 - Pilot")

    def test_dvd_by_size(self):
        disc = {"type": "DVD disc", "titles": [T(0, 6640, byt=4515041280, segments="1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20"),
                                               T(1, 1328, byt=902762496, segments="1,2,3,4"), T(2, 1328, byt=902615040, segments="1,2,3,4")]}
        m = discdb.match(DVD_ENTRY, disc)
        self.assertTrue(m["ok"], m["reason"])
        self.assertEqual({p["id"]: p["episode"] for p in m["picks"]}, {2: "1", 1: "2"})

    def test_mismatch_falls_back(self):
        disc = {"type": "Blu-ray disc", "titles": [T(0, 3030, 11.1, source="00201.mpls")]}
        m = discdb.match(SERIES_ENTRY, disc)
        self.assertFalse(m["ok"])
        self.assertIn("nicht gefunden", m["reason"])

    def test_movie_and_lookup_order(self):
        entry = {"format": "Blu-Ray", "media": {"title": "10 Cloverfield Lane", "year": 2016, "type": "Movie"},
                 "titles": [{"source_file": "00800.mpls", "duration": "1:43:34", "size": 28558835712, "item": {"title": "10 Cloverfield Lane", "type": "MainMovie"}}]}
        calls = []

        def fake(url, timeout=15):
            calls.append(url)
            if "/api/discid/" in url:
                return 404, b""
            return 200, json.dumps(entry).encode()
        discdb._cache.clear()
        with mock.patch.object(discdb, "_http_get", fake):
            e, via = asyncio.run(discdb.lookup("A" * 40, "B" * 32))
        self.assertEqual((via, len(calls)), ("Inhalts-Hash", 2))
        m = discdb.match(e, {"type": "Blu-ray disc", "titles": [T(0, 6214, 28.5, source="00800.mpls"), T(1, 6214, 28.5, source="00801.mpls")]})
        self.assertEqual([p["id"] for p in m["picks"]], [0])
        self.assertEqual(plan.names_from_db(m), ("10 Cloverfield Lane (2016)", {0: "10 Cloverfield Lane (2016)"}))


class ChooseTest(unittest.TestCase):
    def test_movie_with_extras(self):
        d = choose.decide({"type": "Blu-ray disc", "name": "INCEPTION", "titles": [T(0, 8880, 35), T(1, 1500, 2), T(2, 1260, 1.5), T(3, 300, 0.3)]})
        self.assertEqual((d["mode"], d["picks"]), ("movie", [0]))

    def test_series_dvd_without_playall(self):
        eps = [2652, 2620, 2695, 2601, 2648]
        titles = [T(i, s, 1 + i / 10) for i, s in enumerate(eps)] + [T(5, sum(eps[:4]), 4.4), T(6, 190, 0.1)]
        d = choose.decide({"type": "DVD disc", "name": "THE_WALKING_DEAD_S1_D1", "titles": titles}, content_bytes=8e9)
        self.assertEqual((d["mode"], sorted(d["picks"]), d["playall"]), ("series", [0, 1, 2, 3, 4], [5]))

    def test_kids_short_episodes_unsure_all(self):
        titles = [T(i, 660 + i * 5, 0.4) for i in range(8)]
        d = choose.decide({"type": "DVD disc", "name": "KINDER", "titles": titles})
        self.assertEqual((d["mode"], len(d["picks"])), ("unsure", 8))

    def test_long_episodes_unsure_all(self):
        d = choose.decide({"type": "Blu-ray disc", "name": "SHERLOCK_S1", "titles": [T(0, 5280, 20), T(1, 5340, 20), T(2, 5300, 20), T(3, 600, 1)]},
                          content_bytes=45e9)
        self.assertEqual((d["mode"], sorted(d["picks"])), ("unsure", [0, 1, 2, 3]))

    def test_movie_label_with_season_marker_is_unsure(self):
        d = choose.decide({"type": "Blu-ray disc", "name": "SHOW_S2_D4", "titles": [T(0, 5400, 20), T(1, 1500, 2)]}, content_bytes=30e9)
        self.assertEqual(d["mode"], "unsure")

    def test_obfuscated_playlists_manual(self):
        titles = [T(i, 7200 + (i % 3), 30, segments=f"{i},{i + 1}") for i in range(40)]
        d = choose.decide({"type": "Blu-ray disc", "name": "FILM", "titles": titles}, content_bytes=40e9)
        self.assertEqual((d["mode"], d["picks"]), ("manual", []))

    def test_dedupe_same_segments(self):
        titles = [T(0, 7200, 30, segments="1,2,3"), T(1, 7200, 30, segments="3,2,1"), T(2, 600, 1, segments="9")]
        d = choose.decide({"type": "Blu-ray disc", "name": "FILM", "titles": titles}, content_bytes=40e9)
        self.assertEqual((d["mode"], d["picks"], d["dropped"]), ("movie", [0], [1]))

    def test_tmdb_hint_vetoes_movie(self):
        d = choose.decide({"type": "Blu-ray disc", "name": "FILM", "titles": [T(0, 7200, 30), T(1, 600, 1)]}, content_bytes=40e9, hint="series")
        self.assertEqual(d["mode"], "unsure")


if __name__ == "__main__":
    unittest.main()
