# Status PE (Jellyfin filing) – as of 2026-10-10

Mockup done: docs/mockups/paket-e.html (switch "no TMDB key" at the top right; desktop and 375 px for each view)

## Done (backend complete, interface waits for mockup approval)
- `app/media/` (package, loads itself automatically): `conf.py` (settings `media`, folder check), `naming.py` (Jellyfin naming, pure functions), `detect.py` (detection, Play-All, episode proposal), `metadata.py` (TMDB client with cache), `scan.py`/`analyze.py` (selection → detection + TMDB), `plan.py` (preview), `organize.py`+`moves.py` (execute, never overwrite, copy with size check, undo), `series.py` (episode state per series), `store.py` (accompanying data under `DATA/media/`), `auto.py` (automation, default off), `jellyfin.py` (trigger scan), `info.py`, `api.py`.
- Tests (`python -m unittest discover -s tests -t .`, 65 tests, no extra package): naming, detection, TMDB client against the local stub `scripts/tmdb_mock.py`, plan/execute/undo in temp folders, automation decision.
- Checked live against the dev instance (port 8840, TMDB stub 8841): rip hook writes accompanying data, detection (incl. Play-All, also with partial selection), search/IMDb resolution, plan, execute, undo, automation after rip (5 episodes filed, Play-All stays), folder selection/check.
- Sources of the naming rules: https://jellyfin.org/docs/general/server/media/movies/ and .../shows/ (retrieved 2026-10-10): `Title (Year) [imdbid-tt…]`, versions ` - 1080p`, extras folders (extras, behind the scenes, deleted scenes, featurettes, interviews, scenes, shorts, trailers, samples, clips, other), `Season 01`, `S01E01-E02`, specials `Season 00`, forbidden characters `< > : " / \ | ? *`.

## Interface (mockup approved, implemented 1:1)
- `css/media.css`, `js/media.js` (registration), `js/media-settings.js` (settings section `media`), `js/media-wizard.js` + `js/media-steps.js` (wizard, 5 steps), `js/media-util.js` (own request function with readable 422 messages). All < 400 lines.
- Library action `organize` ("In Filme/Serien einsortieren …"): `when(files)` = ≥ 1 file, not in progress/locked; `run(files)` takes several files (the server also resolves folder paths). After executing and undoing: `emit('files-changed')`.
- Small addition compared with the mockup: link "Letzte Aktionen / Rückgängig …" in step 1 (otherwise undo would only be reachable right after filing); in the plan a "… - 2" decision can be set back to "Überspringen"; input field "Start bei Episode" next to "Staffel für alle".
- Checked (dev instance, with PB's settings page on top): settings (folder check, folder selection, switch, TMDB test, delete key, save per section, state "no key"), wizard series with Play-All, film with search, without key by hand, conflict (skip/"- 2"), locked file, execute, undo; desktop 1440 and 375 px, console error-free. Not checked: grid/folder action in PF's new library (does not exist yet), real NAS operation, real TMDB.
- The section is registered as `media` (`registerSettingsSection`, order 40, icon, description); save per section via PB (`collect()` = `{media:{…}}`, secret fields `null` = unchanged; own controls trigger `change`).

## Interfaces offered
Everything under `/api/media` (dev examples). Settings: namespace `media` {movies_dir, series_dir, naming: jellyfin|unveraendert, action: verschieben|kopieren, tmdb_key*, language, id_tags, episode_names, jellyfin_url, jellyfin_key*, jellyfin_scan, auto} (*secret, GET returns `tmdb_key_set`).
- **For PF (grouping):** `GET /api/media/info?path=<rel>` and `POST /api/media/info {"paths":[…]}` → `{"items":[…]}`:
  `{"path":"Serien/…/Season 01/The Walking Dead S01E01.mkv","known":true,"source":"tool|name","kind":"series|movie","title":"The Walking Dead","year":2010,"tmdb":1402,"imdb":"tt1520211","poster":"https://image.tmdb.org/t/p/w342/twd.jpg","season":1,"episode":1,"episode_end":1,"episode_name":"…","role":"episode"}`; unknown: `{"path":…,"known":false}`. `source:"name"` = read from a path in Jellyfin layout (without poster, also for files that were not filed via the tool). Paths: relative to the output folder or absolute. Only this machine knows `poster`/accompanying data (not shared in the cluster).
- **Bulk query for PF (done, tested):** `POST /api/media/infos` with `{"paths":["Serien/…/S01E01.mkv","x/y.mkv"]}` (up to 2000 paths) → the answer is an object **per path**, unknown ones are missing (as requested in PF's status):
  `{"Serien/The Walking Dead (2010) [tmdbid-1402]/Season 01/The Walking Dead S01E01.mkv": {"known":true,"source":"tool","kind":"series","title":"The Walking Dead","year":2010,"tmdb":1402,"imdb":"tt1520211","poster":"https://image.tmdb.org/t/p/w342/twd.jpg","season":1,"episode":1,"episode_end":1,"episode_name":"Days Gone Bye","role":"episode"}}`. The list with all paths (also unknown ones, field `known:false`) is still delivered by `POST /api/media/info` → `{"items":[…]}`.
- `/api/state` → `media`: `{running, undo (ID of the last undoable action|null), configured, tmdb}`; `capabilities.media` = `{v:1, naming:[…]}`.
- Wizard: `POST /detect {paths}` (files or folders) → `{detect:{kind,title,year,season,disc,confidence,reasons,items:[{path,dur,role: episode|playall|movie|extra,…}]}, tmdb:{available,error,candidates,chosen,similarity}, start:{episode,known,estimated}, episodes:{assigned,episode_list,error}, files}`; `GET /search?q=&type=movie|tv&year=` (without key `{available:false}`); `GET /find?imdb=tt…`; `GET /title?type=&id=`; `POST /episodes {items,season,start,tmdb}`; `POST /plan` and `POST /run` (same request: kind,title,year,tmdb,imdb,poster,season,disc,items[{path,role,season,episodes,name,version,extra_kind}],decisions{path:skip|rename}); `GET /run/{id}` (progress); `GET /history`; `POST /undo/{id}` (only the last one); `GET /auto` (automation log).
- Checking settings: `GET /check-dir?path=`, `GET /browse?path=`, `POST /mkdir`, `POST /tmdb/test {key?}`, `POST /jellyfin/test {url?,key?}`, `GET /cache`, `POST /cache/clear`.
- Development: `MEDIA_ROOT` (root of the folder selection, otherwise `OUTPUT_MOUNT`/output folder), `MEDIA_TMDB_BASE` (address of the TMDB stub, `python3 scripts/tmdb_mock.py 8841`, key `testkey`).

## Decisions
- Films: ID tag prefers `imdbid`, series `tmdbid` (as ordered), the other one as fallback. `:` becomes ` - `, `? * < >` are dropped, `"` becomes `'`, `/ \ |` become ` - `.
- Posters are loaded by the browser directly from image.tmdb.org (image URL only, no key).
- Moving within the same file system = rename; otherwise copy via a partial file, size check, then remove the original. Conflict = never overwrite (skip or ` - 2`).
- Automation needs a TMDB key, match ≥ 95 %, episode runtimes ±6 min, start episode known, no conflict/lock.

## Needs from others
- PF: selection actions (several files) and folder actions in `library.js`: `registerLibraryAction({when(files), run(files)})` currently only gets rows. The wizard needs multi-selection (files) or folders (the server resolves folders itself: `paths` may contain folders). Also: use `GET/POST /api/media/info` for grouping. Status: open.
- PF/library cache: after filing, files vanish from the output folder; if the movies/series folder lies inside the output folder, they show up there under a new path (cache entries of old paths expire on the next scan). After `POST /run` the interface fires `emit('files-changed')`.
- PZ: no changes to Dockerfile/Compose needed (only the standard library + existing fastapi/pydantic).

## Foreign files touched
None.

## Questions for the user
1. TMDB API key (free at themoviedb.org) for live tests? So far tested only against a stub.
2. Where are the movies and series folders on the NAS (proposal: next to `dump`, e.g. `/mnt/datenstein/Filme` and `/mnt/datenstein/Serien`)?
3. Should the automation (file after ripping without asking) be offered at all, and with which threshold (now 95 %)?

## Addendum (user's answer)
- Preset `movies_dir=/mnt/datenstein/Filme`, `series_dir=/mnt/datenstein/Serien` (default value only; the backend creates nothing). Caution: inside the container the NAS may be called `/mnt/nas` (OUTPUT_MOUNT); if the preset lies outside the mounted target, the plan reports "Der Ordner muss innerhalb des eingehängten Ziels liegen" (instead of crashing), and the user picks the folder again in the settings. PZ/user: check the actual mount path in the container.
- The user will enter the TMDB key later; until then only the stub. Automation stays as built (default off).
