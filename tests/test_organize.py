"""Tests für Plan, Einsortieren und Rückgängig (app/media/plan.py, organize.py) – nur in temporären Ordnern."""
import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from app import files, state
from app.media import conf, info, moves, organize, series, store
from app.media import plan as planner

run = asyncio.run


class OrganizeBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.out, self.lib = t / "out", t / "lib"
        for d in (self.out, self.lib / "Filme", self.lib / "Serien", t / "data"):
            d.mkdir(parents=True)
        self.d = self.out / "The Walking Dead - Disc 1"
        self.d.mkdir()
        for i in range(1, 4):
            (self.d / f"The Walking Dead - Disc 1 - Titel {i:02d}.mkv").write_bytes(b"x" * (100 + i))
        (self.d / "The Walking Dead - Disc 1 - Titel 06.mkv").write_bytes(b"p" * 500)
        self.old_out, self.old_data, self.old_set = files.out_dir, store.DATA, state.settings.get("media")
        files.out_dir = lambda: (self.out, False)
        store.DATA = t / "data"
        store.reset_memory()
        os.environ["MEDIA_ROOT"] = str(self.lib)
        self.set(movies_dir=str(self.lib / "Filme"), series_dir=str(self.lib / "Serien"))
        self.addCleanup(self.restore)

    def restore(self):
        files.out_dir, store.DATA = self.old_out, self.old_data
        state.settings["media"] = self.old_set
        os.environ.pop("MEDIA_ROOT", None)
        store.reset_memory()
        organize.ops.clear()
        self.tmp.cleanup()

    def set(self, **kw):
        state.settings["media"] = {**conf.DEFAULTS, **kw, **{k: v for k, v in (state.settings.get("media") or {}).items() if k not in kw and k in ("movies_dir", "series_dir")}}

    def req(self, **kw):
        base = "The Walking Dead - Disc 1/The Walking Dead - Disc 1 - Titel "
        r = {"kind": "series", "title": "The Walking Dead", "year": 2010, "tmdb": 1402, "imdb": "tt1520211", "poster": "/twd.jpg", "season": 1, "disc": 1,
             "items": [{"path": f"{base}{i:02d}.mkv", "role": "episode", "season": 1, "episodes": [i], "name": f"Folge {i}"} for i in (1, 2, 3)]
                      + [{"path": f"{base}06.mkv", "role": "skip", "why": "Play-All"}], "decisions": {}}
        r.update(kw)
        return r

    async def go(self, req):
        r = await organize.start(req)
        for _ in range(200):
            if organize.ops[r["id"]]["status"] != "running":
                break
            await asyncio.sleep(0.02)
        return r["id"], organize.ops[r["id"]]


class PlanTest(OrganizeBase):
    def test_series_plan(self):
        p = planner.build_plan(self.req())
        self.assertTrue(p["ok"])
        self.assertEqual([r["status"] for r in p["rows"]], ["move", "move", "move", "skip"])
        self.assertEqual(p["rows"][0]["dst"], "The Walking Dead (2010) [tmdbid-1402]/Season 01/The Walking Dead S01E01.mkv")
        self.assertEqual(p["new_dirs"], ["The Walking Dead (2010) [tmdbid-1402]", "The Walking Dead (2010) [tmdbid-1402]/Season 01"])
        self.assertTrue(p["same_fs"])
        self.assertEqual(p["summary"]["move"], 3)

    def test_episode_names_and_no_tags(self):
        self.set(episode_names=True, id_tags=False)
        p = planner.build_plan(self.req())
        self.assertEqual(p["rows"][1]["dst"], "The Walking Dead (2010)/Season 01/The Walking Dead S01E02 - Folge 2.mkv")

    def test_conflict_and_rename(self):
        dst = self.lib / "Serien/The Walking Dead (2010) [tmdbid-1402]/Season 01"
        dst.mkdir(parents=True)
        (dst / "The Walking Dead S01E03.mkv").write_bytes(b"alt")
        p = planner.build_plan(self.req())
        self.assertEqual([r["status"] for r in p["rows"]], ["move", "move", "conflict", "skip"])
        self.assertIn("Existiert schon", p["rows"][2]["why"])
        self.assertFalse(p["new_dirs"])
        p = planner.build_plan(self.req(decisions={self.req()["items"][2]["path"]: "rename"}))
        self.assertEqual(p["rows"][2]["status"], "move")
        self.assertTrue(p["rows"][2]["dst"].endswith("S01E03 - 2.mkv"))

    def test_duplicate_target_in_plan(self):
        r = self.req()
        r["items"][1]["episodes"] = [1]
        p = planner.build_plan(r)
        self.assertEqual(p["rows"][1]["status"], "conflict")

    def test_locked_by_other_instance(self):
        src = self.out / r["items"][0]["path"] if (r := self.req()) else None
        files.lock_path(src).write_text(json.dumps({"inst": "maintux", "t": time.time()}))
        p = planner.build_plan(r)
        self.assertEqual(p["rows"][0]["status"], "locked")
        self.assertEqual(p["summary"]["locked"], 1)

    def test_busy_conversion(self):
        r = self.req()
        state.conversions.append({"origin": "library", "status": "running", "rel": r["items"][1]["path"]})
        self.addCleanup(state.conversions.clear)
        p = planner.build_plan(r)
        self.assertEqual(p["rows"][1]["status"], "locked")
        self.assertIn("konvertiert", p["rows"][1]["why"])

    def test_missing_and_escape(self):
        r = self.req(items=[{"path": "gibts/nicht.mkv", "role": "episode", "season": 1, "episodes": [1]}, {"path": "../../etc/passwd", "role": "episode", "season": 1, "episodes": [2]}])
        p = planner.build_plan(r)
        self.assertEqual([x["status"] for x in p["rows"]], ["missing", "error"])
        self.assertFalse(p["ok"])

    def test_unchanged_naming(self):
        self.set(naming="unveraendert")
        p = planner.build_plan(self.req())
        self.assertEqual(p["rows"][0]["dst"], "The Walking Dead - Disc 1/The Walking Dead - Disc 1 - Titel 01.mkv")

    def test_movie_with_extra(self):
        (self.out / "film.mkv").write_bytes(b"f")
        (self.out / "bonus.mkv").write_bytes(b"b")
        r = {"kind": "movie", "title": "Blade Runner 2049", "year": 2017, "imdb": "tt1856101",
             "items": [{"path": "film.mkv", "role": "movie"}, {"path": "bonus.mkv", "role": "extra", "extra_kind": "featurettes", "name": "Making of"}]}
        p = planner.build_plan(r)
        self.assertEqual([x["dst"] for x in p["rows"]], ["Blade Runner 2049 (2017) [imdbid-tt1856101]/Blade Runner 2049 (2017) [imdbid-tt1856101].mkv",
                                                         "Blade Runner 2049 (2017) [imdbid-tt1856101]/featurettes/Making of.mkv"])

    def test_no_target_folder(self):
        self.set(series_dir="")
        with self.assertRaises(planner.PlanError):
            planner.build_plan(self.req())

    def test_target_outside_root_rejected(self):
        self.set(series_dir="/etc")
        with self.assertRaises(Exception):
            planner.build_plan(self.req())


class RunTest(OrganizeBase):
    def test_move_and_undo(self):
        async def main():
            oid, op = await self.go(self.req())
            return oid, op
        oid, op = run(main())
        self.assertEqual(op["status"], "done", op)
        root = self.lib / "Serien/The Walking Dead (2010) [tmdbid-1402]/Season 01"
        self.assertEqual(sorted(p.name for p in root.iterdir()), [f"The Walking Dead S01E0{i}.mkv" for i in (1, 2, 3)])
        self.assertEqual((root / "The Walking Dead S01E02.mkv").read_bytes(), b"x" * 102)
        self.assertFalse((self.d / "The Walking Dead - Disc 1 - Titel 01.mkv").exists())
        self.assertTrue(self.d.exists())                                  # Play-All liegt noch darin
        self.assertEqual(series.next_episode(series.key("The Walking Dead", 2010, 1402), 1, 2), 4)
        i = info.info_for(str(root / "The Walking Dead S01E02.mkv"))
        self.assertEqual((i["source"], i["title"], i["season"], i["episode"], i["episode_name"]), ("tool", "The Walking Dead", 1, 2, "Folge 2"))
        h = organize.history()
        self.assertEqual(len(h), 1)
        self.assertEqual(organize.last_undoable()["id"], oid)
        res = organize.undo(oid)
        self.assertTrue(res["ok"])
        self.assertTrue((self.d / "The Walking Dead - Disc 1 - Titel 01.mkv").exists())
        self.assertFalse((self.lib / "Serien/The Walking Dead (2010) [tmdbid-1402]").exists())     # neue Ordner entfernt
        self.assertIsNone(series.next_episode(series.key("The Walking Dead", 2010, 1402), 1, 2))
        self.assertIsNone(organize.last_undoable())
        with self.assertRaises(planner.PlanError):
            organize.undo(oid)

    def test_move_everything_removes_empty_source_and_undo_recreates(self):
        (self.d / "The Walking Dead - Disc 1 - Titel 06.mkv").unlink()
        oid, op = run(self.go(self.req()))
        self.assertEqual(op["status"], "done")
        self.assertFalse(self.d.exists())
        self.assertTrue(self.out.exists())
        self.assertTrue(organize.undo(oid)["ok"])
        self.assertTrue((self.d / "The Walking Dead - Disc 1 - Titel 03.mkv").exists())

    def test_copy_keeps_original_and_undo_removes_copy(self):
        self.set(action="kopieren")
        oid, op = run(self.go(self.req()))
        self.assertEqual(op["status"], "done")
        self.assertTrue((self.d / "The Walking Dead - Disc 1 - Titel 01.mkv").exists())
        dst = self.lib / "Serien/The Walking Dead (2010) [tmdbid-1402]/Season 01/The Walking Dead S01E01.mkv"
        self.assertEqual(dst.stat().st_size, 101)
        self.assertEqual([p.name for p in dst.parent.iterdir() if p.name.startswith(".")], [])    # keine Teildateien
        self.assertTrue(organize.undo(oid)["ok"])
        self.assertFalse(dst.exists())
        self.assertTrue((self.d / "The Walking Dead - Disc 1 - Titel 01.mkv").exists())

    def test_cross_device_copy_path(self):
        orig = moves.same_device
        moves.same_device = lambda a, b: False
        self.addCleanup(setattr, moves, "same_device", orig)
        oid, op = run(self.go(self.req()))
        self.assertEqual(op["status"], "done")
        self.assertEqual({r.get("how") for r in op["rows"] if r["status"] == "done"}, {"copy"})
        self.assertFalse((self.d / "The Walking Dead - Disc 1 - Titel 01.mkv").exists())
        self.assertTrue(organize.undo(oid)["ok"])
        self.assertEqual((self.d / "The Walking Dead - Disc 1 - Titel 02.mkv").read_bytes(), b"x" * 102)

    def test_never_overwrites(self):
        dst = self.lib / "Serien/The Walking Dead (2010) [tmdbid-1402]/Season 01"
        dst.mkdir(parents=True)
        (dst / "The Walking Dead S01E02.mkv").write_bytes(b"alt")
        oid, op = run(self.go(self.req()))
        self.assertEqual(op["status"], "done")
        self.assertEqual((dst / "The Walking Dead S01E02.mkv").read_bytes(), b"alt")
        self.assertTrue((self.d / "The Walking Dead - Disc 1 - Titel 02.mkv").exists())     # blieb liegen
        self.assertEqual(len(organize.history()[-1]["rows"]), 2)

    def test_nothing_to_do(self):
        r = self.req()
        for it in r["items"]:
            it["role"] = "skip"
        with self.assertRaises(planner.PlanError):
            run(organize.start(r))

    def test_sidecar_follows_file(self):
        rel = "The Walking Dead - Disc 1/The Walking Dead - Disc 1 - Titel 01.mkv"
        store.remember_rip({"disc": {"name": "TWD", "volume": "V", "titles": [{"id": 0, "duration": 2600}]}, "title": {"id": 0, "duration": 2600}, "rel": rel})
        self.assertEqual(store.sidecar(rel)["disc"]["name"], "TWD")
        oid, op = run(self.go(self.req()))
        new = str((self.lib / "Serien/The Walking Dead (2010) [tmdbid-1402]/Season 01/The Walking Dead S01E01.mkv").resolve())
        self.assertIsNone(store.sidecar(rel))
        self.assertIsNotNone(store.sidecar(new))
        organize.undo(oid)
        self.assertIsNotNone(store.sidecar(rel))


class InfoTest(unittest.TestCase):
    def test_from_name(self):
        i = info.info_for("Film (2021) [imdbid-tt1234567]/Film (2021) [imdbid-tt1234567].mkv")
        self.assertEqual((i["known"], i["source"], i["kind"], i["imdb"]), (True, "name", "movie", "tt1234567"))
        self.assertEqual(info.info_for("Irgendwas/datei.mkv"), {"path": "Irgendwas/datei.mkv", "known": False})


if __name__ == "__main__":
    unittest.main()
