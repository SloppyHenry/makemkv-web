# Status PG (headless mode) – as of 2026-10-11

Branch `paket-g` (from `main` 63738f7). Nothing is pushed, nothing is merged into `main`, nothing is rolled out.

## Behavior
When switched on (Einstellungen → Headless-Modus), after a disc is inserted the following runs without any operation:
1. Analysis (even if "automatisch analysieren" is off).
2. Memory: if the same disc was ripped by hand before (here or on another machine in the cluster), the same titles, names and folders.
3. Read the disc identifiers straight from the device and look them up in TheDiscDB (first disc ID, then content hash). Hit: only the main feature or only the episodes; folder "Title (Year)", episodes "Series S01E02 - Episode title".
3a. No hit, but TMDB knows the name unambiguously (only as a film or only as a series): the title with the film runtime (± 4 %, at least 3 min) or the titles with the season's episode length (± 12 %, at least two). Helps mostly with German releases, which TheDiscDB rarely knows.
3b. Otherwise the structure of the disc. Film = exactly one title of 70 min or more and no series of equally long titles; series = at least two episodes (15–80 min) without a title of 70 min or more, Play-All and extras are dropped. TMDB (if a key exists) serves only as a cross-check of the name.
4. Uncertain: all titles without duplicates (same runtime, size, segments) and without Play-All. If that would be more than twice as much data as there is video data on the disc: rip nothing, "bitte von Hand".
5. Afterwards the disc is always ejected (done, error, "von Hand"). Only a cancellation by the user leaves it in.
If a "von Hand" disc is inserted again, it stays in the drive ("wartet auf Auswahl"); the memory remembers the selection then ripped by hand. Unknown discs can be submitted with "An TheDiscDB melden" (proposal from memory/detection, assignment per title, preview; it is only sent on button press, TheDiscDB checks before publishing).
Optional: convert after ripping with the default preset of the disc type. Log with reasoning in the field "Headless-Modus" (Laufwerke); "Erkennung testen" shows the choice without ripping.

## Files
- New: `app/headless/` (`__init__`, `udf`, `discid`, `discdb`, `choose`, `run`), `js/headless.js`, `css/headless.css`, `tests/test_headless.py`, `tests/udf_build.py`.
- Also: `plan.py`, `memory.py`, `tmdbmatch.py`, `contribute.py`, `js/headless-contribute.js`, `tests/test_headless_more.py`.
- Core: `ext.register_scan_hook` (+ `auto_scan_forced`), `drives.do_scan(auto=…)` calls the hooks, `rip.prepare_rip()` extracted from `api_rip`, `makemkv` delivers `segments` (attribute 26), `main.OPTIONAL_MODULES` + `app.headless`.
- Stub `makemkvcon`: `source`, `segments`, `fail` per title.

## Checked
- Content hash recomputed against two real TheDiscDB entries (Blu-ray "10 Cloverfield Lane", DVD "Bakugan Vol. 1"): identical.
- UDF reader: hdiutil images (UDF 1.02/1.50, Blu-ray and DVD structure) and own UDF 2.50 image with metadata partition; disc ID and hash as expected.
- Live against thediscdb.com (`scripts/dev.sh`, stub with a Cloverfield image and an equally long decoy playlist): hit via the content hash, only `00800.mpls` ripped, as "10 Cloverfield Lane (2016)".
- Flow in the stub: series disc (5 episodes, Play-All and extra left out), read error (ejected, "Fehler"), 30 decoy playlists ("von Hand", nothing ripped, ejected), children's series with 11-min episodes (uncertain, all titles).
- Interface at 1440 and 375 px without console errors and without horizontal overflow.
- Memory in the stub: unknown disc → "von Hand"; inserted again → stays in; title 8 ripped by hand as "Mein Film (2020)"; inserted again → exactly this title with name and folder. Query to other machines via unit test.
- TMDB (stub `scripts/tmdb_mock.py`): disc "MATRIX" with two long titles → the 136-min title as "Matrix (1999)".
- Report to TheDiscDB: proposal and preview against the stub, sending only via unit test (no test data sent to TheDiscDB).
- `python3 -m unittest discover -s tests -t .`: 182 tests green (9 skipped). No file over 400 lines.

## Open
- Test with a real disc in the drive (DVD, Blu-ray, UHD): reading `/dev/sr0` in the container, disc ID and hit in TheDiscDB.
- Check the thresholds of the structure detection and the TMDB match against own discs (film, series DVD, series Blu-ray).
- Memory across two real, paired machines (so far only a unit test).
- The submission uses TheDiscDB's open "Engram" interface (still without a key there, "TODO: API key"); if it gets a key, the report has to be adapted. Please check the first real report together.
